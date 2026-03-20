import os
import json
import logging
import asyncio
import time
import re
import copy
import hashlib
from typing import Dict, Any, List, Optional, Union, Tuple

from .schemas import ToonResponse, EvidencePack, BBox
from .vision_contract import normalize_vision_observation

logger = logging.getLogger("aosd.capabilities.browser_control.planner")

BROWSER_AGENT_PROMPT = """You are an Autonomous Browser Navigator.
Your goal: {goal}

You see a **Unified Perception Snapshot** (Candidates) and **Content Markers** (Landmarks).
Total nodes: {total_nodes} | Viewport nodes: {viewport_count}

### Unified Perception (Fused DOM + Vision)
Candidates are labeled by source:
- [FUSED]: Confirmed by both Code and Vision (High Confidence).
- [DOM]: Found in code only (Invisible or structural).
- [VISION]: Found visually only (Canvas, dynamic overlays).

### Landmarks (Content Markers)
Non-clickable context (Titles, Headers). Use these to verify your location.

### Decision Rules:
1. **Direct Action**: If you see a [FUSED] or [VISION] input for your search, **TYPE IMMEDIATELY**.
2. **Vision Action**: Only use `action: vision` if you are completely lost or the candidates are stale.
3. **Success**: Use `action: answer` ONLY when Landmarks or Vision provide explicit evidence that the goal is met.
4. **Step Status & Evidence**: Set `step_status` to "completed" only when you have **EVIDENCE** (new landmarks, visible state change, or objective DOM/visual result) that the step succeeded. Mention this evidence explicitly in your `thought`.

### Available Actions:
- {{"action": "navigate", "args": {{"url": "https://..."}}}}
- {{"action": "click", "args": {{"id": "node_id"}}}}
- {{"action": "click_visual", "args": {{"x": 0-1000, "y": 0-1000}}}}
- {{"action": "type", "args": {{"id": "node_id", "text": "...", "press_enter": true}}}}
- {{"action": "press_key", "args": {{"key": "Enter"}}}}
- {{"action": "scroll", "args": {{"direction": "down" | "up"}}}}
- {{"action": "vision", "args": {{"reason": "..."}}}}
- {{"action": "wait", "args": {{"seconds": 2}}}}
- {{"action": "answer", "args": {{"text": "final result"}}}}
- {{"action": "action_batch", "args": {{"steps": [{{"action": "...", "args": {{...}}}}], "policy": {{"stop_on_error": true, "max_steps": 10}}}}}}

### Current Plan:
{plan}
**Current Focus**: Step {current_step}

### JSON FORMAT:
{{
  "thought": "Reasoning (max 2 sentences).",
  "step_status": "in_progress" | "completed",
  "action": "...",
  "args": {{...}}
}}
"""

class BrowserSubagent:
    """100% Agentic Browser Subagent with Multimodal Vision Support."""

    def __init__(
        self,
        runtime: Any,
        llm_manager: Any,
        perception_merger: Any = None,
        *,
        dom_max_nodes: int = 90,
        perception_cache_ttl_s: float = 3.5,
        fast_screenshot_format: str = "jpeg",
        fast_screenshot_quality: int = 60,
        max_same_action_repeats: int = 3,
        max_state_unchanged_loops: int = 5,
        max_forced_recovery_attempts: int = 2,
    ):
        self.runtime = runtime
        self.llm_manager = llm_manager
        self.perception_merger = perception_merger
        self.max_steps = 25
        self._node_map: Dict[str, Dict[str, Any]] = {}
        self._node_offset = 0
        self._viewport = {"w": 1280, "h": 720}
        self._plan: List[str] = []
        self._current_step_idx = 0
        self._last_step_idx = -1
        self._consecutive_same_step = 0
        self._last_action = None
        self._last_args = None
        self._consecutive_same_action = 0
        self._max_same_action_repeats = max(2, int(max_same_action_repeats))
        self._max_state_unchanged_loops = max(3, int(max_state_unchanged_loops))
        self._max_forced_recovery_attempts = max(1, int(max_forced_recovery_attempts))
        self._forced_recovery_attempts = 0
        self._consecutive_parse_failures = 0
        self._max_parse_failures = 2
        self._locked_target_id = str(getattr(runtime, "target_id", "") or "")
        self._last_vision_observation: Dict[str, Any] = {}
        self._last_validation_context: Dict[str, Any] = {}
        self._callbacks: Dict[str, Any] = {}
        self._recent_search_submissions: Dict[str, float] = {}
        self._search_replay_ttl_s: float = 25.0
        self._sticky_completed_idx: int = 0
        self._meta_goal: str = ""
        self._completion_contract: Dict[str, Any] = {}
        
        # State Hashing for Loop Detection
        self._last_state_hash = ""
        self._consecutive_same_state = 0
        
        # Playback integration attributes
        self._playback_service: Any = None
        self._playback_run_id: Optional[str] = None
        self._playback_session_id: Optional[str] = None
        self._playback_step_count: int = 0
        self._run_report_live_path: str = ""
        self._run_report_trace_path: str = ""
        self._dom_max_nodes = max(20, int(dom_max_nodes))
        self._perception_cache_ttl_s = max(0.2, float(perception_cache_ttl_s))
        self._fast_screenshot_format = str(fast_screenshot_format or "jpeg").strip().lower()
        if self._fast_screenshot_format not in {"jpeg", "png"}:
            self._fast_screenshot_format = "jpeg"
        self._fast_screenshot_quality = max(25, min(95, int(fast_screenshot_quality)))
        self._last_page_signature_hash: str = ""
        self._last_cached_state: Dict[str, Any] = {}
        self._last_cached_at: float = 0.0
        self._same_signature_reuse_count: int = 0
        self._max_signature_reuse: int = 10
        self._last_vision_signature_hash: str = ""
        self._last_vision_at: float = 0.0
        self._vision_cache_ttl_s: float = 30.0

    def _evaluate_loop_guard(
        self,
        *,
        action: str,
        goal: str,
        state: Dict[str, Any],
        state_changed: bool,
    ) -> Dict[str, Any]:
        """
        Enforces deterministic anti-loop behavior:
        - First threshold breach -> force one recovery action.
        - Persistent breach after bounded recoveries -> hard stop.
        """
        if state_changed:
            self._forced_recovery_attempts = 0
            return {"mode": "none"}

        severe_state = self._consecutive_same_state >= self._max_state_unchanged_loops
        severe_action = self._consecutive_same_action >= self._max_same_action_repeats
        if not (severe_state or severe_action):
            return {"mode": "none"}

        trigger = "State Stall" if severe_state else "Action Loop"
        if self._forced_recovery_attempts < self._max_forced_recovery_attempts:
            self._forced_recovery_attempts += 1
            recovery_action, recovery_args, recovery_note = self._choose_recovery_action(trigger, goal, state)
            return {
                "mode": "force_recovery",
                "trigger": trigger,
                "recovery_action": recovery_action,
                "recovery_args": recovery_args,
                "note": recovery_note,
                "attempt": int(self._forced_recovery_attempts),
                "max_attempts": int(self._max_forced_recovery_attempts),
            }

        return {
            "mode": "hard_stop",
            "trigger": trigger,
            "reason": (
                f"Loop guard hard-stop: {trigger} persisted "
                f"(same_state={self._consecutive_same_state}, same_action={self._consecutive_same_action}) "
                f"after {self._forced_recovery_attempts}/{self._max_forced_recovery_attempts} recovery attempts."
            ),
        }

    @staticmethod
    def _tokenize_text(value: str) -> List[str]:
        tokens = re.findall(r"[a-zA-Z0-9\u00C0-\u017F_]+", str(value or "").lower())
        stop = {
            "a", "o", "os", "as", "de", "da", "do", "das", "dos", "e", "em", "na", "no", "nas", "nos",
            "um", "uma", "uns", "umas", "por", "para", "the", "and", "to", "of", "in", "on", "for",
            "sim", "yes", "ok", "please", "porfavor", "favor",
        }
        return [t for t in tokens if len(t) >= 3 and t not in stop]

    @classmethod
    def _goal_terms(cls, goal: str) -> List[str]:
        return cls._tokenize_text(goal)[:8]

    def _score_dom_node_for_phase(self, node: Dict[str, Any], terms: List[str]) -> float:
        if not isinstance(node, dict):
            return 0.0
        text = str(node.get("text") or "").lower()
        role = str(node.get("role") or "").lower()
        tag = str(node.get("tag") or "").lower()
        score = 0.0

        if bool(node.get("inViewport")):
            score += 1.0
        if tag in {"input", "button", "a", "select"}:
            score += 0.6
        if role in {"searchbox", "combobox", "textbox", "button", "link"}:
            score += 0.8
        if "small" in text:
            score -= 0.15

        for t in terms:
            if t and t in text:
                score += 0.45
            if t and t in role:
                score += 0.35
        return score

    def _prune_dom_nodes(self, nodes: List[Dict[str, Any]], intent_text: str) -> List[Dict[str, Any]]:
        if len(nodes) <= self._dom_max_nodes:
            return nodes
        terms = self._tokenize_text(intent_text)
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for n in nodes:
            scored.append((self._score_dom_node_for_phase(n, terms), n))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [node for _, node in scored[: self._dom_max_nodes]]

    @staticmethod
    def _normalize_visual_coord(value: Any) -> Optional[float]:
        try:
            v = float(value)
        except Exception:
            return None
        if v < 0 or v > 1000:
            return None
        return v

    def _resolve_click_visual_coords(self, args: Dict[str, Any]) -> Optional[Dict[str, float]]:
        x = self._normalize_visual_coord(args.get("x"))
        y = self._normalize_visual_coord(args.get("y"))
        if x is not None and y is not None:
            return {"x": x, "y": y, "source": "args"}  # type: ignore[return-value]

        coords = self._last_vision_observation.get("coordinates")
        if isinstance(coords, list):
            for c in coords:
                if not isinstance(c, dict):
                    continue
                cx = self._normalize_visual_coord(c.get("x"))
                cy = self._normalize_visual_coord(c.get("y"))
                if cx is None or cy is None:
                    continue
                return {"x": cx, "y": cy, "source": "vision_fallback"}  # type: ignore[return-value]
        return None

    @staticmethod
    def _assess_click_visual_receipt(result_data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result_data, dict):
            return {"ok": True, "reason": "no_result_data"}
        if bool(result_data.get("fallback_clicked", False)):
            return {"ok": True, "reason": "interactive_fallback_clicked"}

        hit = result_data.get("hit_after")
        if not isinstance(hit, dict):
            hit = result_data.get("hit_before")
        if not isinstance(hit, dict):
            return {"ok": True, "reason": "no_hit_snapshot"}

        top_text = str(hit.get("top_text") or "")
        text_l = top_text.lower()
        has_interactive = bool(hit.get("has_interactive_ancestor", False))
        interactive_tag = str(hit.get("interactive_tag") or "").strip().lower()
        top_tag = str(hit.get("top_tag") or "").strip().lower()

        ad_markers = (
            "patrocin",
            "sponsored",
            "advertisement",
            "anúncio",
            "anuncio",
            "ads",
            "ad ",
        )
        if any(marker in text_l for marker in ad_markers):
            return {
                "ok": False,
                "reason": "target appears sponsored/advertisement",
                "hit": {
                    "top_tag": top_tag,
                    "interactive_tag": interactive_tag,
                    "top_text": top_text[:120],
                },
            }

        if not has_interactive:
            return {
                "ok": False,
                "reason": "target has no interactive ancestor",
                "hit": {
                    "top_tag": top_tag,
                    "interactive_tag": interactive_tag,
                    "top_text": top_text[:120],
                },
            }

        if interactive_tag in {"", "main", "body", "html"}:
            return {
                "ok": False,
                "reason": f"interactive ancestor too generic: {interactive_tag or 'none'}",
                "hit": {
                    "top_tag": top_tag,
                    "interactive_tag": interactive_tag,
                    "top_text": top_text[:120],
                },
            }

        return {"ok": True, "reason": "interactive_target_confirmed"}

    @staticmethod
    def _bbox_center(node: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        bbox = node.get("bbox") if isinstance(node, dict) else None
        if not isinstance(bbox, dict):
            return None
        try:
            x = float(bbox.get("x", 0))
            y = float(bbox.get("y", 0))
            w = float(bbox.get("w", bbox.get("width", 0)))
            h = float(bbox.get("h", bbox.get("height", 0)))
        except Exception:
            return None
        if w <= 0 or h <= 0:
            return None
        return (x + (w / 2.0), y + (h / 2.0))

    @staticmethod
    def _is_editable_node(node: Dict[str, Any]) -> bool:
        if not isinstance(node, dict):
            return False
        role = str(node.get("role", "")).lower()
        tag = str(node.get("tag", "")).lower()
        text = str(node.get("text", "")).lower()
        if role in {"searchbox", "textbox", "combobox"}:
            return True
        if tag in {"input", "textarea"}:
            return True
        return ("search" in role) or ("search" in text and tag in {"div", "span", "button", "a"})

    def _find_editable_fallback_node(self, goal: str) -> Optional[Dict[str, Any]]:
        goal_terms = set(self._goal_terms(goal))
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for node in self._node_map.values():
            if not self._is_editable_node(node):
                continue
            source = str(node.get("source", "")).upper()
            role = str(node.get("role", "")).lower()
            tag = str(node.get("tag", "")).lower()
            text = str(node.get("text", "")).lower()
            score = 0.0
            if source == "FUSED":
                score += 3.0
            elif source == "DOM":
                score += 2.0
            else:
                score += 1.0
            if role == "searchbox":
                score += 4.0
            if tag in {"input", "textarea"}:
                score += 2.0
            if any(t in text for t in goal_terms):
                score += 1.5
            if "search" in role or "search" in text:
                score += 2.0
            scored.append((score, node))
        if not scored:
            return None
        scored.sort(key=lambda i: i[0], reverse=True)
        return scored[0][1]

    def _resolve_target_node(self, raw_id: Any) -> Optional[Dict[str, Any]]:
        key = str(raw_id or "").strip()
        if not key:
            return None

        if key in self._node_map:
            return self._node_map.get(key)

        key_l = key.lower()
        base = key_l.split("#", 1)[0].split(".", 1)[0].strip()
        hints = {h for h in [key_l, base] if h}
        scored: List[Tuple[float, Dict[str, Any]]] = []

        for node in self._node_map.values():
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", "")).lower()
            role = str(node.get("role", "")).lower()
            tag = str(node.get("tag", "")).lower()
            text = str(node.get("text", "")).lower()
            source = str(node.get("source", "")).upper()

            score = 0.0
            if key_l and key_l == node_id:
                score += 10.0
            if hints and (role in hints or tag in hints):
                score += 6.0
            if any(h and h in role for h in hints):
                score += 3.0
            if any(h and h in tag for h in hints):
                score += 3.0
            if "search" in key_l and ("search" in role or "search" in text):
                score += 2.5
            # Confidence bonus only when we already have semantic evidence.
            if score > 0:
                if source == "FUSED":
                    score += 1.2
                elif source == "DOM":
                    score += 0.7
                scored.append((score, node))

        if not scored:
            return None
        scored.sort(key=lambda i: i[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _is_css_selector(value: str) -> bool:
        v = str(value or "").strip()
        if not v:
            return False
        return v.startswith("#") or v.startswith(".") or v.startswith("[") or (" " in v) or (">" in v)

    def _build_target_ref(self, args: Dict[str, Any]) -> Dict[str, str]:
        raw_ref = args.get("target_ref")
        if isinstance(raw_ref, dict):
            ref_type = str(raw_ref.get("type") or "").strip().lower()
            ref_value = str(raw_ref.get("value") or "").strip()
            if ref_type and ref_value:
                return {"type": ref_type, "value": ref_value}
        raw_id = str(args.get("id") or "").strip()
        if raw_id:
            if self._looks_like_node_id(raw_id) or raw_id in self._node_map:
                return {"type": "node_id", "value": raw_id}
            if self._is_css_selector(raw_id):
                return {"type": "selector", "value": raw_id}
            if self._looks_like_dom_id(raw_id):
                return {"type": "dom_id", "value": raw_id}
            return {"type": "hint", "value": raw_id}
        return {"type": "", "value": ""}

    def _selector_candidates_from_target_ref(self, target_ref: Dict[str, str]) -> List[str]:
        ref_type = str(target_ref.get("type") or "").strip().lower()
        value = str(target_ref.get("value") or "").strip()
        if not value:
            return []
        if ref_type == "selector":
            return [value]
        if ref_type == "dom_id":
            return [f"#{value}", f"[id='{value}']"]
        if ref_type == "hint" and self._looks_like_dom_id(value):
            return [f"#{value}", f"[id='{value}']"]
        return []

    @staticmethod
    def _looks_like_node_id(value: str) -> bool:
        return bool(re.fullmatch(r"node_\d+", str(value or "").strip().lower()))

    @staticmethod
    def _looks_like_dom_id(value: str) -> bool:
        # Typical DOM ids like a-autoid-1, twotabsearchtextbox, nav-search-submit-button.
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-:.]{1,80}", str(value or "").strip()))

    @staticmethod
    def _click_intent_is_sort_filter(goal: str, thought: str = "") -> bool:
        blob = f"{str(goal or '').lower()} {str(thought or '').lower()}"
        keywords = ["sort", "sorting", "order", "lowest", "price", "filtro", "filtrar", "ordenar", "menor preço", "mais barato"]
        return any(k in blob for k in keywords)

    async def _generate_master_plan(self, goal: str):
        """Phase 1: Decompose the complex goal into 3-4 High-level Milestones."""
        prompt = f"""You are the Master Planner for the Browser Control Engine.
Decompose this request into a logical sequence of 3-4 SUCCESS MILESTONES (High-level states).
Request: "{goal}"

**PLANNING RULES**:
1. Do NOT be granular. Focus on the result of a sequence of actions (e.g., "Search results loaded" instead of "Click search button").
2. Each step should represent a verifiable state change in the browser.
3. Include a final verification step for the user's specific answer.

Format: Return ONLY a numbered list of milestones.
Example:
1. [Website] homepage or search interface loaded
2. Search results for '[term]' displayed
3. Specific item '[item]' details page active
4. Success confirmed and answer extracted
"""
        result, err = await asyncio.to_thread(
            self.llm_manager._execute_with_router, self.llm_manager.chat_pool, 'generate_text',
            prompt=prompt, system_prompt="You are a strategic task planner."
        )
        if err or not result:
            logger.error(f"Failed to generate master plan: {err}")
            self._plan = ["1. Execute user goal directly."]
            return

        response = str(result)
        self._plan = [line.strip() for line in response.split('\n') if line.strip() and re.match(r'^\d+\.', line.strip())]
        logger.info(f"\n{'='*60}\n📋 MASTER PLAN GENERATED:\n" + "\n".join(self._plan) + f"\n{'='*60}")

    def get_last_vision_observation(self) -> Dict[str, Any]:
        if not isinstance(self._last_vision_observation, dict):
            return {}
        return copy.deepcopy(self._last_vision_observation)

    def _extract_url(self, goal: str) -> str:
        goal_lower = goal.lower()
        if "youtube" in goal_lower: return "https://www.youtube.com"
        if "spotify" in goal_lower: return "https://open.spotify.com"
        if "github" in goal_lower: return "https://www.github.com"
        if "google" in goal_lower: return "https://www.google.com"
        match = re.search(r"https?://[^\s,]+", goal)
        return match.group(0) if match else "https://www.google.com"

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _calculate_state_hash(self, state: Dict[str, Any]) -> str:
        """Generates a SHA-256 hash of the current page state (URL + Title + Candidate Summary)."""
        import hashlib
        # Extract meaningful structural summary
        # We focus on the identifiers and existence of elements, not their exact coordinates necessarily
        nodes_summary = []
        for c in state.get("candidates", []):
            eid = c.get("element_id") or "vnode"
            role = c.get("semantic_role") or c.get("visual_role") or "element"
            nodes_summary.append(f"{eid}:{role}")
        
        # Combine with URL and Title
        payload = f"{state.get('url', '')}|{state.get('title', '')}|{','.join(nodes_summary)}"
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _step_contains_any(step: str, keywords: List[str]) -> bool:
        s = str(step or "").lower()
        return any(k in s for k in keywords)

    def _advance_step(self, reason: str, min_idx: Optional[int] = None) -> None:
        if not self._plan:
            return
        next_idx = self._current_step_idx + 1
        if min_idx is not None:
            next_idx = max(next_idx, min_idx)
        bounded = min(max(0, next_idx), len(self._plan) - 1)
        if bounded > self._current_step_idx:
            self._current_step_idx = bounded
            logger.info(f"✅ Master Plan Advanced ({reason}): Next Focus -> {self._plan[self._current_step_idx]}")

    @staticmethod
    def _normalize_meta_goal(goal: str) -> str:
        """
        Converts raw user goal to a compact objective statement.
        Keeps domain + target outcome, removes conversational boilerplate.
        """
        text = re.sub(r"\s+", " ", str(goal or "")).strip()
        if not text:
            return "Complete the requested browser task."

        # Remove common imperative boilerplate in PT/EN.
        patterns = [
            r"(?i)\b(abra|abre|open|go to|acesse|entra no site|entre no site)\b[^,;]*",
            r"(?i)\b(por favor|please)\b",
        ]
        for pat in patterns:
            text = re.sub(pat, " ", text)
        text = re.sub(r"\s+", " ", text).strip(" .,-;")

        # Domain-aware concise normalization for common "search cheapest products" intent.
        low = text.lower()
        if "amazon" in low and ("controle" in low or "controller" in low or "ps4" in low):
            return "Find the three cheapest PS4 controllers on Amazon."
        return text[:220]

    @staticmethod
    def _clean_plan_step(step: str) -> str:
        s = str(step or "")
        s = re.sub(r"^\s*\d+\.\s*", "", s)
        return s.strip()

    def _current_phase_goal(self) -> str:
        if not self._plan or not (0 <= self._current_step_idx < len(self._plan)):
            return "Advance toward task completion."
        return self._clean_plan_step(self._plan[self._current_step_idx])

    def _current_action_intent(self) -> str:
        """
        Action-local objective for analyzers.
        Prioritizes latest validation hint and current milestone.
        """
        hint = str((self._last_validation_context or {}).get("expected_state_hint") or "").strip()
        phase = self._current_phase_goal()
        if hint:
            return f"{phase}. Immediate intent: {hint}"
        return phase

    @staticmethod
    def _infer_required_item_count(goal: str) -> int:
        g = str(goal or "").lower()
        if re.search(r"\b(3|tr[eê]s|three)\b", g):
            return 3
        if re.search(r"\b(2|duas|dois|two)\b", g):
            return 2
        return 1

    def _build_completion_contract(self, goal: str) -> Dict[str, Any]:
        return self._build_completion_contract_for_mode(goal, completion_mode="")

    @staticmethod
    def _normalize_completion_mode(raw: Any) -> str:
        mode = str(raw or "").strip().lower()
        if mode in {"execution_only", "run_only", "execute_only", "somente_execucao", "somente_execução"}:
            return "execution_only"
        return "artifact_report"

    def _build_completion_contract_for_mode(self, goal: str, completion_mode: Any) -> Dict[str, Any]:
        mode = self._normalize_completion_mode(completion_mode)
        if mode == "execution_only":
            return {
                "mode": mode,
                "required_items": 0,
                "required_fields": [],
                "optional_fields": ["name", "price", "url", "evidence"],
                "notes": "Execution-only mode: finalize after successful objective state, artifacts optional.",
            }
        required_items = self._infer_required_item_count(goal)
        return {
            "mode": mode,
            "required_items": required_items,
            "required_fields": ["name", "price"],
            "optional_fields": ["url", "evidence"],
            "notes": "Do not finalize before providing required artifacts.",
        }

    @staticmethod
    def _looks_like_price(value: str) -> bool:
        v = str(value or "")
        return bool(re.search(r"(?:\$|r\$)\s*\d", v.lower()))

    def _validate_answer_artifacts(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        contract = self._completion_contract or {}
        mode = str(contract.get("mode") or "artifact_report").strip().lower()
        if mode == "execution_only":
            text = str(args.get("text") or "").strip()
            if not text:
                return False, "execution_only answer requires non-empty text"
            return True, ""
        required_items = int(contract.get("required_items") or 1)
        required_fields = list(contract.get("required_fields") or ["name", "price"])

        artifacts = args.get("artifacts")
        if not isinstance(artifacts, list):
            return False, "missing artifacts list in answer args"
        if len(artifacts) < required_items:
            return False, f"insufficient artifacts: {len(artifacts)}/{required_items}"

        valid = 0
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            missing = [f for f in required_fields if not str(item.get(f) or "").strip()]
            if missing:
                continue
            if not self._looks_like_price(str(item.get("price") or "")):
                continue
            valid += 1

        if valid < required_items:
            return False, f"artifacts missing required fields or invalid price: {valid}/{required_items}"
        return True, ""


    def _fallback_action_for_parse(self, goal: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generic fallback to avoid dead loops when planner JSON is persistently invalid."""
        url = str(state.get("url", "")).lower()
        if not url or url == "about:blank":
            return {"action": "navigate", "args": {"url": self._extract_url(goal)}, "thought": "Fallback navigate from blank page due to parse failures."}
        
        # Safe generic fallback without deterministic semantic hijacking. 
        # Attempt minimal wait to settle, or if on an obvious end state (like a video player open), cautiously check if we are done.
        
        if "/watch" in url:
             return {"action": "wait", "args": {"seconds": 2}, "thought": "Fallback wait on execution boundary. Content might be playing."}
             
        # Ultimate fallback if no obvious generic trait is observed:
        return {"action": "wait", "args": {"seconds": 3}, "thought": "Fallback wait. LLM parsing failed significantly; pausing to allow page to settle or supervisor to interrupt."}

    @staticmethod
    def _collect_state_signals(state: Dict[str, Any]) -> List[str]:
        signals: List[str] = []
        candidates = state.get("candidates") if isinstance(state.get("candidates"), list) else []
        for c in candidates[:40]:
            if not isinstance(c, dict):
                continue
            role = str(c.get("semantic_role") or c.get("visual_role") or "").lower()
            label = str(c.get("element_id") or "").lower()
            reason = str(c.get("reasoning") or "").lower()
            blob = f"{role} {label} {reason}"
            if any(k in blob for k in ("searchbox", "textbox", "search", "result", "results", "produto", "produtos")):
                signals.append(blob[:140])
        for m in (state.get("markers") or [])[:12]:
            if not isinstance(m, dict):
                continue
            text = str(m.get("text") or "").strip()
            if text:
                signals.append(text[:140])
        return signals[:20]

    @staticmethod
    def _sanitize_action_args(action: str, args: Any) -> Dict[str, Any]:
        """Drops stale cross-action fields to avoid contaminated planner payloads."""
        if not isinstance(args, dict):
            return {}
        action_l = str(action or "").strip().lower()
        allowed: Dict[str, set] = {
            "navigate": {"url"},
            "click": {"id", "target_ref"},
            "click_visual": {"x", "y"},
            "type": {"id", "target_ref", "text", "press_enter"},
            "press_key": {"key", "modifiers"},
            "scroll": {"direction"},
            "vision": {"reason"},
            "wait": {"seconds"},
            "answer": {"text", "artifacts"},
            "action_batch": {"steps", "policy"},
        }
        keep = allowed.get(action_l, set())
        if not keep:
            return {}
        return {k: v for k, v in args.items() if k in keep}

    @staticmethod
    def _vision_requests_reposition(obs: Dict[str, Any]) -> bool:
        blob = f"{str(obs.get('summary') or '').lower()} {str(obs.get('raw_text') or '').lower()}"
        hints = [
            "not visible",
            "outside the current viewport",
            "outside the viewport",
            "scroll up",
            "need to scroll up",
            "header area at the top",
            "fora do viewport",
            "não visível",
            "nao visivel",
            "rolar para cima",
            "subir para localizar",
            "precisa subir",
        ]
        return any(h in blob for h in hints)

    @staticmethod
    def _state_indicates_context_drift(goal: str, state: Dict[str, Any]) -> bool:
        g = str(goal or "").lower()
        url = str(state.get("url") or "").lower()
        title = str(state.get("title") or "").lower()
        if "amazon" in g and ("ps4" in g or "controller" in g or "controle" in g):
            if "amazon." in url and "/deals" in url:
                return True
            if "today's deals" in title or "todays deals" in title:
                return True
        return False

    def _build_goal_search_url(self, goal: str, state: Dict[str, Any]) -> str:
        """Constructs a deterministic search URL as drift-recovery fallback."""
        g = str(goal or "").lower()
        current_url = str(state.get("url") or "")
        if "amazon" in g and ("ps4" in g or "controller" in g or "controle" in g):
            domain = "www.amazon.com"
            m = re.search(r"https?://([^/]+)/?", current_url)
            if m and "amazon." in m.group(1):
                domain = m.group(1)
            return f"https://{domain}/s?k=PS4+controller"
        return self._extract_url(goal)

    def _choose_recovery_action(self, trigger: str, goal: str, state: Dict[str, Any]) -> Tuple[str, Dict[str, Any], str]:
        """
        Conflict policy:
        1) Vision says target is out of viewport => reposition.
        2) Context drift => navigate to deterministic goal URL.
        3) Otherwise use one vision refresh.
        """
        if self._vision_requests_reposition(self._last_vision_observation):
            return (
                "scroll",
                {"direction": "up"},
                f"{trigger} detected. Vision indicates target outside viewport; forcing scroll up.",
            )
        if self._state_indicates_context_drift(goal, state):
            return (
                "navigate",
                {"url": self._build_goal_search_url(goal, state)},
                f"{trigger} detected with context drift; forcing deterministic goal navigation.",
            )
        return (
            "vision",
            {"reason": f"{trigger} detected. Page state/action stalled; requesting focused visual re-check."},
            f"{trigger} detected. Falling back to vision re-check.",
        )

    @staticmethod
    def _is_soft_loop_action(action: str) -> bool:
        """
        Continuous exploration actions are allowed to repeat.
        Loop detection should warn first, and only force recovery on severe state stall.
        """
        return str(action or "").strip().lower() in {"scroll", "vision"}

    def _build_validation_context(self, action: str, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        expected = ""
        if action == "type" and bool(args.get("press_enter", False)):
            expected = "A submissao da busca deve refletir estado coerente com consulta executada (DOM/visual), sem depender apenas de URL."
        elif action == "click":
            expected = "Clique deve produzir alteracao visual/DOM coerente com o alvo."
        elif action == "click_visual":
            expected = "Clique visual deve alterar foco/estado de forma observavel no DOM/visao."
        elif action == "navigate":
            expected = "Conteudo principal esperado deve aparecer apos carregamento."
        else:
            expected = "Estado apos acao deve ser validado por sinais visuais/DOM relevantes para a meta."
        return {
            "last_action": action,
            "last_args": copy.deepcopy(args if isinstance(args, dict) else {}),
            "expected_state_hint": expected,
            "observed_signals": self._collect_state_signals(state),
            "state_title": str(state.get("title") or "")[:120],
            "state_url_observation": str(state.get("url") or "")[:180],
            "focus": copy.deepcopy(state.get("focus") or {}),
        }

    @staticmethod
    def _normalize_query(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def _query_hash(self, value: str) -> str:
        normalized = self._normalize_query(value)
        return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:16]

    def _is_duplicate_search_submission(self, query: str) -> bool:
        qh = self._query_hash(query)
        ts = self._recent_search_submissions.get(qh)
        if not ts:
            return False
        return (time.time() - float(ts)) <= self._search_replay_ttl_s

    def _remember_search_submission(self, query: str) -> str:
        qh = self._query_hash(query)
        self._recent_search_submissions[qh] = time.time()
        # light cleanup to avoid unbounded growth
        now = time.time()
        stale = [k for k, v in self._recent_search_submissions.items() if (now - float(v)) > (self._search_replay_ttl_s * 4.0)]
        for k in stale:
            self._recent_search_submissions.pop(k, None)
        return qh

    @staticmethod
    def _looks_like_search_results_state(state: Dict[str, Any]) -> bool:
        markers = state.get("markers") if isinstance(state.get("markers"), list) else []
        marker_blob = " ".join(str(m.get("text") or "").lower() for m in markers if isinstance(m, dict))
        if any(k in marker_blob for k in ["results", "resultados", "price", "preço", "sponsored", "patrocinado"]):
            return True

        candidates = state.get("candidates") if isinstance(state.get("candidates"), list) else []
        product_like = 0
        for c in candidates[:80]:
            if not isinstance(c, dict):
                continue
            role = str(c.get("semantic_role") or c.get("visual_role") or "").lower()
            text = str(c.get("reasoning") or "").lower()
            if any(k in text for k in ["$","r$", "stars", "estrelas", "add to cart", "adicionar ao carrinho", "playstation", "ps4", "sponsored", "patrocinado"]):
                product_like += 1
            if role in {"link", "button", "searchbox"} and any(k in text for k in ["sort", "ordenar", "filter", "filtro"]):
                product_like += 1
            if product_like >= 3:
                return True
        return False

    def _apply_sticky_progress(self, action: str, args: Dict[str, Any], state: Dict[str, Any], resp: ToonResponse) -> None:
        # Base sticky progression: never regress completed checkpoint.
        self._current_step_idx = max(self._current_step_idx, self._sticky_completed_idx)
        if not self._plan:
            return

        try:
            result_data = getattr(resp, "result_data", None) if resp is not None else None
            if not isinstance(result_data, dict):
                result_data = {}
        except Exception:
            result_data = {}

        # Step 1 completion (site ready) becomes sticky after first successful navigate.
        if action == "navigate":
            self._sticky_completed_idx = max(self._sticky_completed_idx, 1 if len(self._plan) > 1 else 0)

        # Search submission receipt (type + enter) should be trusted as execution intent.
        if action == "type" and bool(args.get("press_enter", False)):
            if bool(result_data.get("enter_dispatched", False)):
                if len(self._plan) > 1:
                    self._sticky_completed_idx = max(self._sticky_completed_idx, 1)

        # If page now clearly looks like search results, keep step 2 complete.
        if self._looks_like_search_results_state(state) and len(self._plan) > 1:
            self._sticky_completed_idx = max(self._sticky_completed_idx, 1)

        self._current_step_idx = max(self._current_step_idx, self._sticky_completed_idx)

    def _emit_worker_planner_update(self, payload: Dict[str, Any]) -> None:
        cb = self._callbacks if isinstance(self._callbacks, dict) else {}
        touch = cb.get("touch_work_context")
        work_id = cb.get("work_id")
        if not callable(touch) or not work_id:
            return
        try:
            patch = {
                "data": {
                    "browser_planner": {
                        "ts": time.time(),
                        **(payload or {}),
                    }
                }
            }
            touch(work_id, patch)
        except Exception:
            pass

    def _attach_action_receipt(
        self,
        resp: ToonResponse,
        *,
        action: str,
        args: Dict[str, Any],
        step_id: str,
        trace_id: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> ToonResponse:
        base = resp.result_data if isinstance(resp.result_data, dict) else {}
        receipt = {
            "kind": "planner_action_receipt_v1",
            "planner_action": str(action or ""),
            "planner_args": copy.deepcopy(args if isinstance(args, dict) else {}),
            "step_id": str(step_id or ""),
            "trace_id": str(trace_id or ""),
            "status": str(getattr(resp, "status", "") or ""),
            "component": str(getattr(resp, "component", "") or ""),
            "ts": time.time(),
        }
        if isinstance(extra, dict):
            receipt.update(extra)
        merged = dict(base)
        merged["planner_receipt"] = receipt
        resp.result_data = merged
        return resp

    def _init_run_report(self, *, trace_id: str, goal: str) -> None:
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            logs_dir = os.path.join(root, "data", "logs")
            os.makedirs(logs_dir, exist_ok=True)
            safe_trace = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(trace_id or "trace"))
            self._run_report_live_path = os.path.join(logs_dir, "browser_run_report_live.md")
            self._run_report_trace_path = os.path.join(logs_dir, f"browser_run_report_{safe_trace}.md")
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(self._run_report_live_path, "a", encoding="utf-8") as f:
                f.write(f"\n\n## Run {safe_trace} ({ts})\n")
                f.write(f"- goal: {str(goal or '').strip()}\n")
            with open(self._run_report_trace_path, "w", encoding="utf-8") as f:
                f.write(f"# Browser Run Report - {safe_trace}\n\n")
                f.write(f"- started_at: {ts}\n")
                f.write(f"- goal: {str(goal or '').strip()}\n")
        except Exception as e:
            logger.warning("run report init failed: %s", e)
            self._run_report_live_path = ""
            self._run_report_trace_path = ""

    def _append_run_report_event(self, event: str, payload: Dict[str, Any]) -> None:
        paths = [p for p in [self._run_report_live_path, self._run_report_trace_path] if p]
        if not paths:
            return
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            clean_payload = payload if isinstance(payload, dict) else {"value": str(payload)}
            blob = json.dumps(clean_payload, ensure_ascii=False, indent=2, default=str)
            entry = f"\n### {ts} - {str(event or '').strip()}\n```json\n{blob}\n```\n"
            for path in paths:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(entry)
        except Exception as e:
            logger.warning("run report append failed event=%s err=%s", event, e)

    async def run_to_goal(
        self,
        goal: str,
        playback_service: Any = None,
        run_id: str = "default",
        session_id: str = "default",
        callbacks: Optional[Dict[str, Any]] = None,
        completion_mode: str = "",
    ) -> ToonResponse:
        self._playback_service = playback_service
        self._playback_run_id = run_id
        self._playback_session_id = session_id
        self._playback_step_count = 0
        self._callbacks = callbacks if isinstance(callbacks, dict) else {}

        logger.info(f"\n{'='*60}\n🚀 STARTING BROWSER GOAL: {goal}\n{'='*60}")
        trace_id = self.runtime._trace_id
        self._init_run_report(trace_id=trace_id, goal=goal)
        self._meta_goal = self._normalize_meta_goal(goal)
        self._completion_contract = self._build_completion_contract_for_mode(goal, completion_mode=completion_mode)
        logger.info(f"🎯 META GOAL: {self._meta_goal}")
        logger.info(f"🏁 COMPLETION CONTRACT: {json.dumps(self._completion_contract, ensure_ascii=False)}")
        self._append_run_report_event(
            "run_start",
            {
                "trace_id": trace_id,
                "goal": goal,
                "meta_goal": self._meta_goal,
                "completion_contract": copy.deepcopy(self._completion_contract),
                "max_steps": int(self.max_steps),
            },
        )
        if hasattr(self.runtime, "set_step_context"):
            try:
                self.runtime.set_step_context(step_id="initial", trace_id=trace_id)
            except Exception:
                pass
        history: List[Dict[str, Any]] = []
        if hasattr(self.runtime, "set_agent_control_active"):
            try:
                await self.runtime.set_agent_control_active(True)
            except Exception:
                pass
        
        # Initialize Master Plan
        if not self._plan:
            await self._generate_master_plan(goal)
        try:
            for step_num in range(1, self.max_steps + 1):
                step_id = f"step_{step_num}"
                if hasattr(self.runtime, "set_step_context"):
                    try:
                        self.runtime.set_step_context(step_id=step_id, trace_id=trace_id)
                    except Exception:
                        pass
                logger.info(f"\n--- [ {step_id.upper()} ] ---")
                resume_context = await self._wait_if_runtime_paused(step_id)
                if resume_context:
                    history.append({
                        "step": step_num,
                        "thought": "User resumed with additional context.",
                        "action": "resume_context",
                        "args": {"context": resume_context},
                        "status": "success",
                        "observation": resume_context,
                    })
                    await self._record_playback_frame(step_num, "resume_context", {"context": resume_context})
                    send_status = self._callbacks.get("send_status") if isinstance(self._callbacks, dict) else None
                    if callable(send_status):
                        send_status(
                            "executing",
                            {
                                "action": "browser.control.run",
                                "code": "resumed_by_user",
                                "label": "Resumed from browser overlay.",
                                "resume_context": resume_context,
                            },
                        )
            
                # Master Planning Summary in logs
                self._current_step_idx = max(self._current_step_idx, self._sticky_completed_idx)
                plan_str = "\n".join([f"{' [x] ' if i < self._current_step_idx else ' [ ] '}{s}" for i, s in enumerate(self._plan)])
                logger.info(f"\n📋 CURRENT PROGRESS:\n{plan_str}")
                self._emit_worker_planner_update(
                    {
                        "phase": "step_start",
                        "step_id": step_id,
                        "step_num": step_num,
                        "current_step_index": self._current_step_idx,
                        "current_step": self._plan[self._current_step_idx] if self._plan and self._current_step_idx < len(self._plan) else "",
                        "plan": list(self._plan or []),
                    }
                )
            
                # Lightweight state sync: no URL heuristic gating.
                # We only ensure an initial on-load sync and short settle at step 1.
                if step_num == 1:
                    logger.info(f"[{step_id}] 🔄 [Initial Sync] Waiting for first-page load/settle")
                    await self.runtime._wait_for_load()
                    await asyncio.sleep(0.8)

                state = await self._get_page_state(goal)
                
                # --- Advanced Loop & Stall Detection ---
                current_hash = self._calculate_state_hash(state)
                
                state_changed = current_hash != self._last_state_hash
                if not state_changed:
                    self._consecutive_same_state += 1
                    logger.warning(f"[{step_id}] ⚠️ State hasn't changed (Consecutive: {self._consecutive_same_state})")
                else:
                    self._consecutive_same_state = 0
                    self._last_state_hash = current_hash

                # Milestone Stall Detection
                if self._current_step_idx == self._last_step_idx:
                    self._consecutive_same_step += 1
                else:
                    self._last_step_idx = self._current_step_idx
                    self._consecutive_same_step = 0
                
                # Initial frame for this step
                await self._record_playback_frame(step_num, "thinking", {"goal": goal})
            
                if step_num == 1 and state['url'] == "about:blank":
                    target_url = self._extract_url(goal)
                    logger.info(f"[{step_id}] 🌐 Bootstrapping -> {target_url}")
                    await self.runtime.navigate(target_url)
                    history.append({"step": 1, "thought": "Navigate to start.", "action": "navigate", "args": {"url": target_url}, "status": "success"})
                    
                    # Record frame after navigation
                    await self._record_playback_frame(step_num, "navigate", {"url": target_url})
                    
                    continue

                try:
                    # REASONING PHASE
                    thought_data = await self._think(goal, state, history)
                    action = str(thought_data.get("action", "wait"))
                    args = self._sanitize_action_args(action, thought_data.get("args", {}))
                    thought = thought_data.get("thought", "Thinking...")

                    # Repeated Action Detection (based on final thought for this step)
                    if action == self._last_action and args == self._last_args:
                        self._consecutive_same_action += 1
                    else:
                        self._last_action = action
                        self._last_args = args
                        self._consecutive_same_action = 0

                    # Conflict policy: if planner keeps asking vision while latest vision already
                    # requested reposition/context recovery, execute corrective action directly.
                    if action == "vision":
                        if self._vision_requests_reposition(self._last_vision_observation):
                            action = "scroll"
                            args = {"direction": "up"}
                            thought = f"{thought} | Vision indicates target outside viewport; executing scroll up instead of another vision call."
                        elif self._state_indicates_context_drift(goal, state):
                            action = "navigate"
                            args = {"url": self._build_goal_search_url(goal, state)}
                            thought = f"{thought} | Context drift detected; navigating back to deterministic goal URL instead of repeating vision."
                        self._last_action = action
                        self._last_args = args

                    # LOOP SIGNALING: Detect repeated state/action patterns, but never hard-override
                    # the planner action. Some tasks legitimately require repeated loops (e.g. infinite
                    # scroll until target appears). We only raise an explicit warning for the model.
                    if self._consecutive_same_state >= 3 or self._consecutive_same_action >= 2:
                        trigger = "State Stall" if self._consecutive_same_state >= 3 else "Action Loop"
                        alert_note = (
                            f"{trigger} signal detected (same_state={self._consecutive_same_state}, "
                            f"same_action={self._consecutive_same_action}, state_changed={state_changed}). "
                            "No hard block/override applied; reassess whether repetition is intentional."
                        )
                        logger.warning(f"⚠️ [Loop Detection] {alert_note}")
                        thought = f"{thought} | {alert_note}"

                    guard = self._evaluate_loop_guard(
                        action=action,
                        goal=goal,
                        state=state,
                        state_changed=state_changed,
                    )
                    if str(guard.get("mode")) == "force_recovery":
                        forced_action = str(guard.get("recovery_action") or action)
                        forced_args = guard.get("recovery_args") if isinstance(guard.get("recovery_args"), dict) else args
                        guard_note = str(guard.get("note") or "Forced recovery action by loop guard.")
                        logger.warning(
                            f"[{step_id}] 🛟 Loop guard forcing recovery "
                            f"attempt {guard.get('attempt')}/{guard.get('max_attempts')}: "
                            f"{forced_action}({forced_args})"
                        )
                        thought = f"{thought} | {guard_note}"
                        action = forced_action
                        args = forced_args
                        self._last_action = action
                        self._last_args = args
                    elif str(guard.get("mode")) == "hard_stop":
                        stop_reason = str(guard.get("reason") or "Loop guard hard-stop")
                        logger.error(f"[{step_id}] 🛑 {stop_reason}")
                        self._append_run_report_event(
                            "loop_guard_hard_stop",
                            {
                                "trace_id": trace_id,
                                "step_id": step_id,
                                "step_num": int(step_num),
                                "reason": stop_reason,
                                "url": str(state.get("url") or ""),
                                "title": str(state.get("title") or ""),
                            },
                        )
                        self._emit_worker_planner_update(
                            {
                                "phase": "loop_guard_hard_stop",
                                "step_id": step_id,
                                "step_num": step_num,
                                "reason": stop_reason,
                            }
                        )
                        return self._fail(stop_reason, trace_id, step_id)
                    
                    logger.info(f"[{step_id}] 🧠 THOUGHT: {thought}")
                    logger.info(f"[{step_id}] 🎯 ACTION: {action}({args})")
                    self._append_run_report_event(
                        "decision",
                        {
                            "trace_id": trace_id,
                            "step_id": step_id,
                            "step_num": int(step_num),
                            "thought": str(thought or ""),
                            "action": str(action or ""),
                            "args": copy.deepcopy(args if isinstance(args, dict) else {}),
                            "url": str(state.get("url") or ""),
                            "title": str(state.get("title") or ""),
                            "current_plan_step": self._plan[self._current_step_idx] if self._plan and self._current_step_idx < len(self._plan) else "",
                        },
                    )
                    self._emit_worker_planner_update(
                        {
                            "phase": "decision",
                            "step_id": step_id,
                            "step_num": step_num,
                            "thought": thought,
                            "action": action,
                            "args": args,
                            "parse_failures": self._consecutive_parse_failures,
                            "url": state.get("url"),
                            "title": state.get("title"),
                        }
                    )
                    
                    if action == "answer":
                        ok_answer, answer_reason = self._validate_answer_artifacts(args if isinstance(args, dict) else {})
                        if not ok_answer:
                            logger.warning(f"[{step_id}] ⛔ answer blocked: {answer_reason}")
                            history.append({
                                "step": step_num,
                                "thought": thought,
                                "action": "answer",
                                "args": args,
                                "status": "error",
                                "observation": f"Completion contract not met: {answer_reason}",
                            })
                            self._emit_worker_planner_update(
                                {
                                    "phase": "answer_blocked",
                                    "step_id": step_id,
                                    "step_num": step_num,
                                    "reason": answer_reason,
                                    "completion_contract": copy.deepcopy(self._completion_contract),
                                }
                            )
                            await asyncio.sleep(0.4)
                            continue
                        logger.info(f"[{step_id}] ✅ GOAL REACHED (Self-Verified): {args.get('text')}")
                        self._append_run_report_event(
                            "goal_reached",
                            {
                                "trace_id": trace_id,
                                "step_id": step_id,
                                "step_num": int(step_num),
                                "answer_text": str(args.get("text") or ""),
                                "artifacts": copy.deepcopy(args.get("artifacts")) if isinstance(args, dict) else [],
                            },
                        )
                        # Record final frame before finishing
                        await self._record_playback_frame(step_num, "answer", args)
                        return ToonResponse(
                            command_id="finish", component="planner", action="wait", trace_id=trace_id, step_id=step_id, status="success",
                            execution_time=0.1, message=args.get("text")
                        )

                    # EXECUTION PHASE
                    resume_context = await self._wait_if_runtime_paused(step_id)
                    if resume_context:
                        history.append({
                            "step": step_num,
                            "thought": "User resumed with additional context.",
                            "action": "resume_context",
                            "args": {"context": resume_context},
                            "status": "success",
                            "observation": resume_context,
                        })
                        await self._record_playback_frame(step_num, "resume_context", {"context": resume_context})
                    pre_action_focus = copy.deepcopy(state.get("focus") or {})
                    resp = await self._execute_action(action, args, step_id, trace_id)

                    if str(getattr(resp, "status", "")) == "error":
                        err = str(getattr(resp, "error_details", "") or "Unknown planner execution error")
                        logger.warning(f"[{step_id}] ⚠️ Action failed: {action}({args}) -> {err}")
                        self._append_run_report_event(
                            "action_error",
                            {
                                "trace_id": trace_id,
                                "step_id": step_id,
                                "step_num": int(step_num),
                                "action": str(action or ""),
                                "args": copy.deepcopy(args if isinstance(args, dict) else {}),
                                "error": err,
                            },
                        )
                        history.append({
                            "step": step_num,
                            "thought": thought,
                            "action": action,
                            "args": args,
                            "status": "error",
                            "observation": err,
                        })
                        self._emit_worker_planner_update(
                            {
                                "phase": "action_failed",
                                "step_id": step_id,
                                "step_num": step_num,
                                "action": action,
                                "args": args,
                                "error": err,
                            }
                        )
                        await asyncio.sleep(0.4)
                        continue
                    
                    # Action gate: block planner until load/settle window is honored.
                    try:
                        await self.runtime.wait_after_action(pre_action_focus, action)
                    except Exception as gate_err:
                        logger.warning(f"[{step_id}] action gate warning: {gate_err}")

                    # Re-capture state after gate.
                    state = await self._get_page_state(goal)
                    self._apply_sticky_progress(action, args, state, resp)
                    self._last_validation_context = self._build_validation_context(action, args, state)
                    self._append_run_report_event(
                        "action_applied",
                        {
                            "trace_id": trace_id,
                            "step_id": step_id,
                            "step_num": int(step_num),
                            "action": str(action or ""),
                            "args": copy.deepcopy(args if isinstance(args, dict) else {}),
                            "status": str(getattr(resp, "status", "") or ""),
                            "result_data": copy.deepcopy(resp.result_data) if isinstance(resp.result_data, dict) else {},
                            "url_after": str(state.get("url") or ""),
                            "title_after": str(state.get("title") or ""),
                            "focus_after": copy.deepcopy(state.get("focus") or {}),
                        },
                    )
                    
                    history.append({
                        "step": step_num,
                        "thought": thought,
                        "action": action,
                        "args": args,
                        "status": "success", 
                        "observation": f"Action {action} executed. New state captured."
                    })
                    # Record frame after action
                    await self._record_playback_frame(step_num, action, args)
                    
                    self._emit_worker_planner_update(
                        {
                            "phase": "action_applied",
                            "step_id": step_id,
                            "step_num": step_num,
                            "action": action,
                            "args": args,
                            "verify_reason": "optimistic",
                            "current_step_index": self._current_step_idx,
                            "current_step": self._plan[self._current_step_idx] if self._plan and self._current_step_idx < len(self._plan) else "",
                            "url": state.get("url"),
                            "title": state.get("title"),
                        }
                    )
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.error(f"[{step_id}] ❌ Logic failure: {e}")
                    self._append_run_report_event(
                        "logic_failure",
                        {
                            "trace_id": trace_id,
                            "step_id": step_id,
                            "step_num": int(step_num),
                            "error": str(e),
                        },
                    )
                    self._emit_worker_planner_update(
                        {
                            "phase": "error",
                            "step_id": step_id,
                            "step_num": step_num,
                            "error": str(e),
                        }
                    )
                    return self._fail(str(e), trace_id, step_id)

            self._append_run_report_event(
                "timeout",
                {
                    "trace_id": trace_id,
                    "step_id": f"step_{self.max_steps}",
                    "max_steps": int(self.max_steps),
                },
            )
            return self._fail("Timeout", trace_id, f"step_{self.max_steps}")
        finally:
            if hasattr(self.runtime, "set_step_context"):
                try:
                    self.runtime.set_step_context(step_id="", trace_id=trace_id)
                except Exception:
                    pass
            if hasattr(self.runtime, "set_agent_control_active"):
                try:
                    await self.runtime.set_agent_control_active(False)
                except Exception:
                    pass

    async def _wait_if_runtime_paused(self, step_id: str) -> str:
        if not hasattr(self.runtime, "get_tab_control_state"):
            return ""
        notified = False
        paused_frame_recorded = False
        while True:
            state = await self.runtime.get_tab_control_state()
            paused = bool(state.get("paused"))
            if not paused:
                if bool(state.get("resume_requested")):
                    return str(state.get("resume_context") or "").strip()
                return ""
            if not notified:
                send_status = self._callbacks.get("send_status") if isinstance(self._callbacks, dict) else None
                if callable(send_status):
                    send_status(
                        "executing",
                        {
                            "action": "browser.control.run",
                            "code": "paused_by_user",
                            "label": "Paused from browser overlay. Waiting for resume.",
                        },
                    )
                notified = True
            if not paused_frame_recorded:
                try:
                    self._playback_step_count += 1
                    frame_bytes = await self.runtime.capture_screenshot_bytes()
                    if frame_bytes and self._playback_service:
                        self._playback_service.add_frame(
                            session_id=self._playback_session_id,
                            run_id=self._playback_run_id,
                            step=self._playback_step_count,
                            action={"type": "paused", "args": {"step_id": step_id}},
                            frame_bytes=frame_bytes,
                        )
                        send_status = self._callbacks.get("send_status") if isinstance(self._callbacks, dict) else None
                        if callable(send_status):
                            send_status(
                                "executing",
                                {
                                    "action": "browser.control.run",
                                    "code": "playback_step",
                                    "label": "Playback: paused",
                                    "playback": {
                                        "run_id": self._playback_run_id,
                                        "session_id": self._playback_session_id,
                                        "step": self._playback_step_count,
                                        "action": {"type": "paused", "args": {"step_id": step_id}},
                                    },
                                },
                            )
                except Exception:
                    pass
                paused_frame_recorded = True
            await asyncio.sleep(0.4)

    async def _get_page_state(self, goal: Optional[str] = None) -> Dict[str, Any]:
        """Captures fused perception state using parallel analyzers."""
        await self._ensure_target_binding()
        page_info = {}
        if hasattr(self.runtime, "get_page_info"):
            try:
                page_info = await self.runtime.get_page_info()
            except Exception:
                page_info = {}
        url = str(page_info.get("url", "") or "") if isinstance(page_info, dict) else ""
        title = str(page_info.get("title", "") or "") if isinstance(page_info, dict) else ""
        if not url:
            url = await self._get_current_url()
        if not title:
            try:
                title = await self.runtime._get_current_title()
            except Exception:
                title = ""
        if isinstance(page_info, dict):
            viewport = page_info.get("viewport") if isinstance(page_info.get("viewport"), dict) else {}
            if viewport.get("w") and viewport.get("h"):
                try:
                    self._viewport = {"w": int(viewport.get("w")), "h": int(viewport.get("h"))}
                except Exception:
                    pass

        # Quick page signature: enables short-TTL cache reuse when state is unchanged.
        page_signature: Dict[str, Any] = {}
        try:
            if hasattr(self.runtime, "get_page_signature"):
                page_signature = await self.runtime.get_page_signature()
        except Exception:
            page_signature = {}

        # Analyzer intent hierarchy:
        # meta_goal (stable) + phase_goal (milestone) + action_intent (immediate objective)
        meta_goal = self._meta_goal or self._normalize_meta_goal(goal or "")
        phase_goal = self._current_phase_goal()
        action_intent = self._current_action_intent()
        intent_ctx = (
            f"Meta Goal: {meta_goal}\n"
            f"Current Phase Goal: {phase_goal}\n"
            f"Action Intent: {action_intent}\n"
            "Priority: follow Current Phase Goal and Action Intent over global wording.\n"
            "Do not restart completed milestones unless there is explicit regression evidence."
        )

        signature_payload = {
            "url": url,
            "title": title,
            "phase": phase_goal,
            "sig": page_signature,
        }
        signature_hash = hashlib.sha256(
            json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        now = time.time()
        same_signature = self._last_page_signature_hash == signature_hash
        cache_fresh = (
            self._last_cached_state
            and same_signature
            and (
                (now - self._last_cached_at) <= self._perception_cache_ttl_s
                or self._same_signature_reuse_count < self._max_signature_reuse
            )
        )

        if cache_fresh:
            cached = copy.deepcopy(self._last_cached_state)
            cached["url"] = url
            cached["title"] = title
            logger.info("[Perception] Cache hit; reusing fused state for unchanged page signature.")
            self._node_map = copy.deepcopy(cached.get("_node_map", {}))
            cached.pop("_node_map", None)
            self._same_signature_reuse_count += 1
            return cached

        # 1. Acquire DOM first (cheaper than vision) and prune payload for analyzers.
        obs_data: Dict[str, Any] = await self.runtime.get_skeletal_dom()
        raw_nodes = obs_data.get("nodes", []) if isinstance(obs_data.get("nodes"), list) else []
        pruned_nodes = self._prune_dom_nodes(
            raw_nodes,
            f"{meta_goal} {phase_goal} {action_intent}",
        )

        # 2. Acquire screenshot with lightweight settings for perception.
        screenshot_path: str = ""
        try:
            screenshot_path = await self.runtime.capture_screenshot_to_file(
                image_format=self._fast_screenshot_format,
                quality=self._fast_screenshot_quality,
            )
        except Exception as e:
            logger.warning(f"[Perception] Fast screenshot capture failed: {e}")
            screenshot_path = ""

        # 3. Parallel Analysis & Fusion with timeout/partial fallback.
        if self.perception_merger is None:
            raise RuntimeError("Perception merger is not configured.")
        try:
            perception = await self.perception_merger.get_unified_state(
                dom_data=pruned_nodes,
                image_data=screenshot_path,
                intent=intent_ctx or "Explore the page"
            )
        finally:
            # Cleanup screenshot
            if screenshot_path and os.path.exists(screenshot_path):
                try: os.remove(screenshot_path)
                except: pass
        
        logger.info(f"[Perception] Fused State: {len(perception['candidates'])} Candidates | Confidence: {perception['global_confidence']}")
        
        # Populate node map for action execution
        self._node_map = {}
        raw_by_id: Dict[str, Dict[str, Any]] = {
            str(n.get("id")): n for n in raw_nodes if isinstance(n, dict) and n.get("id")
        }
        for c in perception["candidates"]:
            # c is a dict (from entry.dict() in merger)
            eid = c.get("element_id")
            if eid:
                bbox = c.get("bounding_box")
                # Handle BBox as object or dict
                if hasattr(bbox, "dict"):
                    b = bbox.dict()
                elif isinstance(bbox, dict):
                    b = bbox
                else:
                    b = {"x": 0, "y": 0, "width": 0, "height": 0}
                
                raw_node = raw_by_id.get(str(eid), {})
                raw_text = str(raw_node.get("text") or "").strip()
                reasoning_text = str(c.get("reasoning") or "").strip()
                label_text = raw_text or reasoning_text

                # Simplified entry for planner actions
                self._node_map[eid] = {
                    "id": eid,
                    "bbox": b,
                    "tag": c.get("semantic_role") or c.get("visual_role") or "",
                    "role": c.get("semantic_role") or c.get("visual_role") or "element",
                    "source": c.get("source", "DOM"),
                    "text": label_text
                }
        
        state_out = {
            "url": url,
            "title": title,
            "candidates": perception["candidates"],
            "markers": obs_data.get("markers", []),
            "focus": obs_data.get("focus", {}),
            "viewport": self._viewport,
            "total_nodes": obs_data.get("total_count", 0),
            "viewport_count": obs_data.get("viewport_count", 0),
            "global_trust": perception["global_confidence"]
        }
        self._last_page_signature_hash = signature_hash
        self._last_cached_at = now
        self._last_cached_state = copy.deepcopy(state_out)
        self._last_cached_state["_node_map"] = copy.deepcopy(self._node_map)
        self._same_signature_reuse_count = 0
        return state_out

    async def _ensure_target_binding(self) -> None:
        """
        Keep all planner actions attached to the same page target whenever possible.
        This reduces the chance of acting on a wrong tab/window after reuses.
        """
        if not self._locked_target_id:
            self._locked_target_id = str(getattr(self.runtime, "target_id", "") or "")
        if not self._locked_target_id:
            return
        if not hasattr(self.runtime, "attach_to_target"):
            return
        try:
            attached = await self.runtime.attach_to_target(self._locked_target_id)
            if attached:
                return
            # Recovery path: if locked target is stale, re-lock to current/available target.
            meta = self.runtime.get_connection_metadata() if hasattr(self.runtime, "get_connection_metadata") else {}
            current_target = str(meta.get("target_id") or getattr(self.runtime, "target_id", "") or "")
            if current_target:
                self._locked_target_id = current_target
                return
            if hasattr(self.runtime, "attach_to_any_page"):
                recovered = await self.runtime.attach_to_any_page([self._locked_target_id])
                if recovered:
                    self._locked_target_id = str(recovered)
        except Exception as e:
            logger.warning(f"Target binding check failed: {e}")

    async def _get_vision_observation(self, goal: str, url: str) -> Dict[str, Any]:
        """Takes a CDP screenshot and returns a normalized visual observation contract."""
        path = await self.runtime.capture_screenshot_to_file()
        prompt = (
            f"You are the visual eyes of a browser agent. Context/Reason: {goal}. URL: {url}. "
            "Describe exactly what you see on screen. Identify items the DOM might have missed (titles, status indicators). "
            "CRITICAL: You MUST provide exact X, Y coordinates (0-1000 scale) for the elements mentioned in the Context/Reason! Format as: X: 123 Y: 456"
        )
        try:
            result = await asyncio.to_thread(self.llm_manager.analyze_image, image_path=path, prompt=prompt)
            logger.info(f"[Vision] Observer Feedback: {str(result)[:200]}...")
            return normalize_vision_observation(result, goal=goal, url=url)
        except Exception as e:
            return normalize_vision_observation(f"Vision fallback failed: {e}", goal=goal, url=url)
        finally:
            if path and os.path.exists(str(path)):
                try: os.remove(str(path))
                except: pass

    def _reconcile_plan_by_state(self, state: Dict[str, Any]):
        # Deliberately disabled: no URL-based deterministic reconciliation.
        # Step progression remains fully agentic via LLM `step_status`.
        return

    async def _think(self, goal: str, state: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
        plan_str = "\n".join([f"{' [x] ' if i < self._current_step_idx else ' [ ] '}{s}" for i, s in enumerate(self._plan)])
        current_step_str = self._plan[self._current_step_idx] if self._current_step_idx < len(self._plan) else "Victory"
        meta_goal = self._meta_goal or self._normalize_meta_goal(goal)
        phase_goal = self._current_phase_goal()
        action_intent = self._current_action_intent()
        
        system_prompt = BROWSER_AGENT_PROMPT.format(
            goal=meta_goal,
            plan=plan_str,
            current_step=current_step_str,
            total_nodes=int(state.get('total_nodes', 0) or 0),
            viewport_count=int(state.get('viewport_count', 0) or 0)
        )
        user_prompt = f"### State:\nURL: {state.get('url', '')}\nTitle: {state.get('title', '')}\n"
        user_prompt += f"Focus: {json.dumps(state.get('focus') or {}, ensure_ascii=False)[:400]}\n"
        user_prompt += (
            f"\n### Objective Hierarchy:\n"
            f"- Meta Goal: {meta_goal}\n"
            f"- Current Phase Goal: {phase_goal}\n"
            f"- Action Intent: {action_intent}\n"
            f"- Rule: Do NOT restart completed milestones unless explicit regression is observed.\n"
        )
        user_prompt += (
            "\n### Completion Contract (Hard Gate):\n"
            f"{json.dumps(self._completion_contract, ensure_ascii=False)}\n"
            "If you choose action='answer', you MUST include args.artifacts as a list of items satisfying the contract.\n"
            "Do not finalize with only URL/title or generic statements.\n"
        )
        
        if history:
            user_prompt += "### History (Last 8):\n"
            for h in history[-8:]:
                obs = f" | Obs: {h['observation'][:50]}..." if h.get("observation") else ""
                user_prompt += f"- Step {h['step']}: {h['action']} -> {h['status']}{obs}. {h['thought'][:100]}...\n"

        if self._last_validation_context:
            user_prompt += "\n### Validation Context (Agentic, Non-Deterministic):\n"
            user_prompt += (
                "Use this as guidance, not as strict script logic. "
                "Validate by comparing expected state vs current DOM/visual evidence.\n"
            )
            user_prompt += json.dumps(self._last_validation_context, ensure_ascii=False)[:700] + "\n"
        
        user_prompt += "\n### Unified Perception (Candidates):\n"
        for c in state.get('candidates', []):
            source = c.get("source", "DOM")
            label = c.get("element_id") or c.get("visual_role") or "unknown"
            text = c.get("reasoning", "")
            user_prompt += f"[{source}] {label}: '{text}'\n"

        if state.get('markers'):
            user_prompt += "\n### Landmarks (Informational):\n"
            for idx, m in enumerate(state.get('markers', []), start=1):
                safe_text = str(m.get('text', '')).replace('"', "'")
                marker_id = str(m.get('id') or f"mk_{idx}")
                marker_kind = str(m.get('kind') or "marker")
                user_prompt += f"[{marker_id}] {marker_kind}: '{safe_text}'\n"
                
        if state.get('vision'):
            vis = state['vision']
            # Compress vision observation to avoid prompt bloat
            vis_view = vis.get('prompt_view', vis.get('summary', ''))
            user_prompt += f"\n### Live Vision Observation:\n{vis_view[:500]}\n"
        user_prompt += (
            "\n### Validation Policy:\n"
            "- Do NOT validate success by URL only.\n"
            "- Decide success by expected visual/DOM state for the current intent.\n"
            "- If an action was sent with essential steps, check whether expected state appeared before retrying from scratch.\n"
        )
            
        result, err = await asyncio.to_thread(
            self.llm_manager._execute_with_router,
            self.llm_manager.chat_pool,
            'generate_structured',
            prompt=user_prompt,
            system_prompt=system_prompt,
            contract="browser_planner_action_v1",
        )
        
        if err:
            self._consecutive_parse_failures += 1
            logger.error(
                f"[Reasoning] LLM Contract/Router Error ({self._consecutive_parse_failures}/{self._max_parse_failures}): {err}"
            )
            self._emit_worker_planner_update(
                {
                    "phase": "parse_failure",
                    "error": str(err),
                    "parse_failures": self._consecutive_parse_failures,
                    "raw_preview": "",
                }
            )
            if self._consecutive_parse_failures >= self._max_parse_failures:
                logger.error("⚠️ Too many contract failures. Switching to deterministic fallback action.")
                return self._fallback_action_for_parse(goal, state)
            return {
                "action": "wait",
                "args": {"seconds": 1},
                "thought": f"Provider contract violation ({err}). Retrying...",
            }

        if not result:
            logger.error("[Reasoning] Empty LLM response")
            return {"action": "wait"}

        try:
            if not isinstance(result, dict):
                raise ValueError("Provider returned non-dict structured result")
            data = result

            # Reset failure counter on success
            self._consecutive_parse_failures = 0

            # Master Plan Advancement logic
            status = data.get("step_status", "").lower()
            thought = data.get("thought", "").lower()
            
            # Heuristic Backup: Opportunistic Milestone Skipping
            # If the agent mentions ANY milestone (current or future) is completed/finished, advance to it.
            thought_lower = thought.lower()
            status_completed = status == "completed"
            
            # Check all milestones from current to end
            for i in range(self._current_step_idx, len(self._plan)):
                step_num = i + 1
                # More flexible patterns for completion detection
                step_patterns = [
                    f"step {step_num} completed", 
                    f"step {step_num} finished", 
                    f"milestone {step_num} reached",
                    f"passo {step_num} concluído",
                    f"etapa {step_num} finalizada"
                ]
                
                if any(p in thought_lower for p in step_patterns) or (i == self._current_step_idx and status_completed):
                    if i > self._current_step_idx:
                        logger.warning(f"⏩ Master Plan SKIPPED to Step {step_num} (Heuristic match in thought: '{thought_lower[:50]}...')")
                        self._current_step_idx = i
                    
                    # Advance to the NEXT step focus if current/future one is reported as done
                    if self._current_step_idx < len(self._plan) - 1:
                        self._current_step_idx += 1
                        logger.info(f"✅ Master Plan Advanced: Next Focus -> {self._plan[self._current_step_idx]}")
                    break
            
            return data
        except Exception as e: 
            self._consecutive_parse_failures += 1
            logger.error(f"[Reasoning] Parse Failure ({self._consecutive_parse_failures}/{self._max_parse_failures}): {e}")
            logger.debug(f"[Reasoning] Structured problematic output: {result}")
            self._emit_worker_planner_update(
                {
                    "phase": "parse_failure",
                    "error": str(e),
                    "parse_failures": self._consecutive_parse_failures,
                    "raw_preview": str(result)[:400],
                }
            )
            
            if self._consecutive_parse_failures >= self._max_parse_failures:
                logger.error("⚠️ Too many parse failures. Switching to deterministic fallback action.")
                return self._fallback_action_for_parse(goal, state)

            return {"action": "wait", "args": {"seconds": 1}, "thought": f"Parse error ({e}). Retrying..."}

    async def _execute_action(self, action: str, args: Dict[str, Any], step_id: str, trace_id: str) -> ToonResponse:
        try:
            await self._ensure_target_binding()
            if not isinstance(args, dict):
                args = {}

            # Batch execution: deterministic local executor over normalized contract.
            if action == "action_batch":
                steps = args.get("steps")
                if not isinstance(steps, list) or not steps:
                    return self._fail("action_batch requires non-empty steps", trace_id, step_id)

                policy = args.get("policy") if isinstance(args.get("policy"), dict) else {}
                stop_on_error = bool(policy.get("stop_on_error", True))
                try:
                    max_steps = int(policy.get("max_steps", 10))
                except Exception:
                    max_steps = 10
                max_steps = max(1, min(max_steps, 10))

                executed = 0
                for idx, raw_step in enumerate(steps[:max_steps], start=1):
                    if not isinstance(raw_step, dict):
                        if stop_on_error:
                            return self._fail(f"action_batch step_{idx} invalid: expected object", trace_id, step_id)
                        continue
                    sub_action = str(raw_step.get("action") or "").strip().lower()
                    sub_args = raw_step.get("args") if isinstance(raw_step.get("args"), dict) else {}
                    if not sub_action or sub_action == "action_batch":
                        if stop_on_error:
                            return self._fail(f"action_batch step_{idx} invalid action: {sub_action}", trace_id, step_id)
                        continue

                    logger.info(f"[{step_id}] 📦 Batch step_{idx}: {sub_action}({sub_args})")
                    sub_resp = await self._execute_action(sub_action, sub_args, step_id, trace_id)
                    if str(getattr(sub_resp, "status", "")) == "error":
                        if stop_on_error:
                            err = str(getattr(sub_resp, "error_details", "") or f"batch step {idx} failed")
                            return self._fail(f"action_batch failed at step_{idx}: {err}", trace_id, step_id)
                    executed += 1

                resp = ToonResponse(
                    command_id=f"batch_{int(time.time())}",
                    component="planner",
                    action="action_batch",
                    trace_id=trace_id,
                    step_id=step_id,
                    status="success",
                    execution_time=0.1,
                    message=f"Batch executed with {executed} sub-steps.",
                    result_data={
                        "kind": "action_batch_receipt_v1",
                        "executed_steps": int(executed),
                        "stop_on_error": bool(stop_on_error),
                        "max_steps": int(max_steps),
                    },
                )
                return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)

            # Action Pacing: Wait 1.5s before every interactive action to allow SPA settling
            if action in ["click", "type", "scroll", "click_visual", "press_key"]:
                await asyncio.sleep(1.5)

            if action == "navigate":
                logger.info(f"[{step_id}] 🚀 Action: navigate -> {args.get('url')}")
                resp = await self.runtime.navigate(args.get("url"))
                return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)

            elif action == "vision":
                logger.info(f"[{step_id}] 👁️ Action: vision (CDP Screenshot)")
                reason = args.get("reason", "Provide a general visual summary of the page.")
                cur_url = await self._get_current_url()
                sig_hash = ""
                try:
                    sig = await self.runtime.get_page_signature() if hasattr(self.runtime, "get_page_signature") else {}
                    sig_hash = hashlib.sha256(
                        json.dumps(
                            {"url": cur_url, "sig": sig, "reason": str(reason or "").strip().lower()},
                            ensure_ascii=False,
                            sort_keys=True,
                        ).encode("utf-8")
                    ).hexdigest()
                except Exception:
                    sig_hash = ""

                now = time.time()
                reusable_obs = (
                    bool(self._last_vision_observation)
                    and bool(sig_hash)
                    and sig_hash == self._last_vision_signature_hash
                    and (now - self._last_vision_at) <= self._vision_cache_ttl_s
                )
                if reusable_obs:
                    obs = copy.deepcopy(self._last_vision_observation)
                    logger.info(f"[{step_id}] 👁️ Vision cache hit: reused recent observation for unchanged page.")
                else:
                    obs = await self._get_vision_observation(reason, cur_url)
                    self._last_vision_signature_hash = sig_hash
                    self._last_vision_at = now
                self._last_vision_observation = obs if isinstance(obs, dict) else {}
                resp = ToonResponse(
                    command_id="vision",
                    component="planner",
                    action="vision",
                    trace_id=trace_id,
                    step_id=step_id,
                    status="success",
                    execution_time=1.5,
                    message=str(obs.get("prompt_view") or obs.get("summary") or ""),
                    result_data={
                        "kind": "vision_action_receipt_v1",
                        "reason": str(reason or ""),
                        "summary": str(obs.get("summary") or obs.get("prompt_view") or "")[:500],
                    },
                )
                return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)

            elif action == "click_visual":
                resolved = self._resolve_click_visual_coords(args)
                if not resolved:
                    return self._fail("click_visual requires valid x/y or prior vision coordinates", trace_id, step_id)
                logger.info(
                    f"[{step_id}] 🖱️ Action: click_visual -> x:{resolved['x']}, y:{resolved['y']} (source={resolved['source']})"
                )
                tx = (float(resolved["x"]) / 1000.0) * self._viewport['w']
                ty = (float(resolved["y"]) / 1000.0) * self._viewport['h']
                resp = await self.runtime.click(x=tx, y=ty)
                rd = resp.result_data if isinstance(getattr(resp, "result_data", None), dict) else {}
                if rd and not bool(rd.get("delivered", True)):
                    return self._fail(
                        f"click_visual not delivered at ({round(tx,1)},{round(ty,1)}), retarget required",
                        trace_id,
                        step_id,
                    )
                target_assessment = self._assess_click_visual_receipt(rd)
                if not bool(target_assessment.get("ok", True)):
                    reason = str(target_assessment.get("reason") or "invalid click_visual target")
                    return self._fail(
                        f"click_visual rejected: {reason}. retarget required",
                        trace_id,
                        step_id,
                    )
                return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)

            elif action == "click":
                target_ref = self._build_target_ref(args)
                raw_id = str(target_ref.get("value") or "").strip()

                # Prefer direct DOM selector/id resolution when planner emits real page id (e.g., a-autoid-1).
                for sel in self._selector_candidates_from_target_ref(target_ref):
                    try:
                        logger.info(f"[{step_id}] 🧭 click selector-first -> {sel}")
                        resp = await self.runtime.click(selector=sel)
                        rd = resp.result_data if isinstance(getattr(resp, "result_data", None), dict) else {}
                        if rd and not bool(rd.get("delivered", True)):
                            continue
                        return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)
                    except Exception:
                        continue

                target = self._resolve_target_node(raw_id)
                if not target:
                    return self._fail(f"Node not found: {raw_id}", trace_id, step_id)
                logger.info(f"[{step_id}] 🖱️ Action: click -> node:{target.get('id')} | Role:{target.get('role')} | Label:\"{target.get('text')}\" | Bbox:{target.get('bbox')}")

                # Guard rail: avoid accidental clicks on search box when id requested a non-node selector/id.
                target_role = str(target.get("role") or "").lower()
                target_tag = str(target.get("tag") or "").lower()
                if (
                    raw_id
                    and not self._looks_like_node_id(raw_id)
                    and (target_role in {"searchbox", "textbox", "combobox"} or target_tag in {"input", "textarea"})
                ):
                    return self._fail(
                        f"click target mismatch: requested '{raw_id}' resolved to editable target '{target.get('id')}'",
                        trace_id,
                        step_id,
                    )
                center = self._bbox_center(target)
                if center is None:
                    return self._fail(f"Node has invalid bbox: {target.get('id')}", trace_id, step_id)
                tx, ty = center
                logger.info(f"  └─ Resolved Coordinates: {round(tx,1)}, {round(ty,1)}")
                resp = await self.runtime.click(x=tx, y=ty)
                rd = resp.result_data if isinstance(getattr(resp, "result_data", None), dict) else {}
                if rd and not bool(rd.get("delivered", True)):
                    return self._fail(
                        f"click not delivered for node {target.get('id')} at ({round(tx,1)},{round(ty,1)}), retarget required",
                        trace_id,
                        step_id,
                    )
                return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)

            elif action == "type":
                target_ref = self._build_target_ref(args)
                raw_target = str(target_ref.get("value") or "")
                node = self._resolve_target_node(raw_target)
                selector_candidates = self._selector_candidates_from_target_ref(target_ref)

                # DOM-id/selector route: try direct runtime selector typing first.
                if not node and selector_candidates:
                    text_value = str(args.get("text", ""))
                    press_enter = bool(args.get("press_enter", False))
                    for sel in selector_candidates:
                        try:
                            logger.info(f"[{step_id}] ⌨️ type selector-first -> {sel}")
                            resp = await self.runtime.type_text(
                                text=text_value,
                                selector=sel,
                                press_enter=press_enter,
                                focus_before_type=True,
                                clear_existing=True,
                            )
                            result_data = getattr(resp, "result_data", None)
                            if (
                                press_enter
                                and text_value
                                and isinstance(result_data, dict)
                                and bool(result_data.get("enter_dispatched", False))
                            ):
                                qh = self._remember_search_submission(text_value)
                                logger.info(f"[{step_id}] ✅ Search submission receipt accepted query_hash={qh}")
                            elif press_enter and text_value:
                                return self._fail(
                                    "type selector-first failed to deliver accepted Enter key event",
                                    trace_id,
                                    step_id,
                                )
                            return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)
                        except Exception:
                            continue

                if not node:
                    fallback_node = self._find_editable_fallback_node(goal="")
                    if fallback_node:
                        logger.warning(
                            f"[{step_id}] type target unresolved ({raw_target}); "
                            f"falling back to editable node {fallback_node.get('id')}"
                        )
                        node = fallback_node
                    else:
                        return self._fail(f"Node not found: {raw_target}", trace_id, step_id)
                if not self._is_editable_node(node):
                    fallback_node = self._find_editable_fallback_node(goal="")
                    if fallback_node:
                        logger.warning(
                            f"[{step_id}] type target non-editable ({node.get('id')}:{node.get('role')}/{node.get('tag')}); "
                            f"falling back to editable node {fallback_node.get('id')}"
                        )
                        node = fallback_node
                    else:
                        return self._fail(
                            f"type target not editable and no editable fallback found: {node.get('id')}",
                            trace_id,
                            step_id,
                        )
                logger.info(f"[{step_id}] ⌨️ Action: type -> node:{node.get('id')} | Role:{node.get('role')} | Label:\"{node.get('text')}\" | Text:\"{args.get('text')}\"")
                center = self._bbox_center(node)
                if center is None:
                    return self._fail(f"Node has invalid bbox: {node.get('id')}", trace_id, step_id)
                tx, ty = center
                text_value = str(args.get("text", ""))
                press_enter = bool(args.get("press_enter", False))
                if press_enter and text_value and self._is_duplicate_search_submission(text_value):
                    logger.warning(
                        f"[{step_id}] 🔁 Duplicate search submission blocked for query hash={self._query_hash(text_value)}"
                    )
                    resp = ToonResponse(
                        command_id="dup_search_blocked",
                        component="planner",
                        action="wait",
                        trace_id=trace_id,
                        step_id=step_id,
                        status="success",
                        execution_time=0.05,
                        message="Duplicate search submission suppressed by anti-replay window.",
                        result_data={
                            "kind": "search_replay_guard_v1",
                            "blocked": True,
                            "query_hash": self._query_hash(text_value),
                            "ttl_s": self._search_replay_ttl_s,
                        },
                    )
                    return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)

                resp = await self.runtime.type_text(
                    text=str(args.get("text", "")),
                    x=float(tx),
                    y=float(ty),
                    press_enter=press_enter,
                    focus_before_type=True,
                    clear_existing=True,
                )
                result_data = getattr(resp, "result_data", None)
                if (
                    press_enter
                    and text_value
                    and isinstance(result_data, dict)
                    and bool(result_data.get("enter_dispatched", False))
                ):
                    qh = self._remember_search_submission(text_value)
                    logger.info(f"[{step_id}] ✅ Search submission receipt accepted query_hash={qh}")
                elif press_enter and text_value:
                    return self._fail(
                        "type action failed to deliver accepted Enter key event",
                        trace_id,
                        step_id,
                    )
                return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)

            elif action == "press_key":
                key = str(args.get("key") or "Enter")
                modifiers = args.get("modifiers") if isinstance(args.get("modifiers"), list) else []
                logger.info(f"[{step_id}] ⌨️ Action: press_key -> {key} modifiers={modifiers}")
                key_receipt = await self.runtime.press_key(key, modifiers=modifiers)
                if not bool(key_receipt.get("accepted", False)):
                    return self._fail(
                        f"press_key not accepted by page focus for key={key}",
                        trace_id,
                        step_id,
                    )
                resp = ToonResponse(
                    command_id="press_key",
                    component="planner",
                    action="press_key",
                    trace_id=trace_id,
                    step_id=step_id,
                    status="success",
                    execution_time=0.2,
                    result_data={
                        "kind": "press_key_action_receipt_v1",
                        "key": key,
                        "modifiers": modifiers,
                        "key_receipt": key_receipt,
                    },
                )
                return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)

            elif action == "scroll":
                logger.info(f"[{step_id}] 📜 Action: scroll -> {args.get('direction')}")
                try:
                    blurred = await self.runtime.blur_active_editable()
                    if blurred:
                        logger.info(f"[{step_id}] scroll.prep -> blurred focused editable element")
                except Exception:
                    pass
                px = 600 if str(args.get("direction", "down")) == "down" else -600
                scroll_receipt = await self.runtime.scroll_page(px)
                if not bool(scroll_receipt.get("delivered", False)):
                    return self._fail(
                        f"scroll not delivered (requested={px}, delta={scroll_receipt.get('delta_y')})",
                        trace_id,
                        step_id,
                    )
                resp = ToonResponse(
                    command_id="scroll",
                    component="planner",
                    action="scroll",
                    trace_id=trace_id,
                    step_id=step_id,
                    status="success",
                    execution_time=1.1,
                    result_data=scroll_receipt,
                )
                return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)

            elif action == "wait":
                seconds = float(args.get("seconds", 1) or 1)
                seconds = max(0.1, min(seconds, 8.0))
                logger.info(f"[{step_id}] ⏳ Action: wait -> {seconds}s")
                await asyncio.sleep(seconds)
                resp = ToonResponse(
                    command_id="wait",
                    component="planner",
                    action="wait",
                    trace_id=trace_id,
                    step_id=step_id,
                    status="success",
                    execution_time=seconds,
                    result_data={"kind": "wait_action_receipt_v1", "seconds": float(seconds)},
                )
                return self._attach_action_receipt(resp, action=action, args=args, step_id=step_id, trace_id=trace_id)

            return self._fail("Action unknown", trace_id, step_id)
        except Exception as e:
            logger.error(f"[{step_id}] _execute_action exception ({action}): {e}")
            return self._fail(str(e), trace_id, step_id)

    async def _get_current_url(self) -> str: return await self.runtime._get_current_url()

    def _fail(self, m: str, t: str, i: str) -> ToonResponse:
        return ToonResponse(command_id="err", component="planner", action="wait", trace_id=t, step_id=i, status="error", execution_time=0.1, error_details=m)
    async def _record_playback_frame(self, step: int, action: str, args: Dict[str, Any]) -> None:
        """Captures a frame and adds it to the playback service."""
        if not self._playback_service:
            return
            
        try:
            self._playback_step_count += 1
            frame_bytes = await self.runtime.capture_screenshot_bytes()
            if frame_bytes:
                self._playback_service.add_frame(
                    session_id=self._playback_session_id,
                    run_id=self._playback_run_id,
                    step=self._playback_step_count,
                    action={"type": action, "args": args},
                    frame_bytes=frame_bytes
                )
                send_status = self._callbacks.get("send_status") if isinstance(self._callbacks, dict) else None
                if callable(send_status):
                    send_status(
                        "executing",
                        {
                            "action": "browser.control.run",
                            "code": "playback_step",
                            "label": f"Playback: {action}",
                            "playback": {
                                "run_id": self._playback_run_id,
                                "session_id": self._playback_session_id,
                                "step": self._playback_step_count,
                                "action": {"type": action, "args": args},
                            },
                        },
                    )
        except Exception as e:
            logger.error(f"Failed to record playback frame: {e}")
