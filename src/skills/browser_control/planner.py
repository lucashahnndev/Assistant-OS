import os
import json
import logging
import asyncio
import time
import re
import copy
from typing import Dict, Any, List, Optional, Union, Tuple

from .schemas import ToonResponse, EvidencePack, BBox
from .runtime import BrowserRuntime
from .vision_contract import normalize_vision_observation

logger = logging.getLogger("aosd.skills.browser_control.planner")

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

    def __init__(self, runtime: Any, llm_manager: Any, perception_merger: Any):
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
        self._consecutive_parse_failures = 0
        self._max_parse_failures = 2
        self._locked_target_id = str(getattr(runtime, "target_id", "") or "")
        self._last_vision_observation: Dict[str, Any] = {}
        self._last_validation_context: Dict[str, Any] = {}
        self._callbacks: Dict[str, Any] = {}
        
        # State Hashing for Loop Detection
        self._last_state_hash = ""
        self._consecutive_same_state = 0
        
        # Playback integration attributes
        self._playback_service: Any = None
        self._playback_run_id: Optional[str] = None
        self._playback_session_id: Optional[str] = None
        self._playback_step_count: int = 0

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
            if source == "FUSED":
                score += 1.2
            elif source == "DOM":
                score += 0.7

            if score > 0:
                scored.append((score, node))

        if not scored:
            return None
        scored.sort(key=lambda i: i[0], reverse=True)
        return scored[0][1]

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
        }

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

    async def run_to_goal(
        self,
        goal: str,
        playback_service: Any = None,
        run_id: str = "default",
        session_id: str = "default",
        callbacks: Optional[Dict[str, Any]] = None,
    ) -> ToonResponse:
        self._playback_service = playback_service
        self._playback_run_id = run_id
        self._playback_session_id = session_id
        self._playback_step_count = 0
        self._callbacks = callbacks if isinstance(callbacks, dict) else {}

        logger.info(f"\n{'='*60}\n🚀 STARTING BROWSER GOAL: {goal}\n{'='*60}")
        trace_id = self.runtime._trace_id
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
                
                if current_hash == self._last_state_hash:
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
                    args = thought_data.get("args", {})
                    thought = thought_data.get("thought", "Thinking...")

                    # Repeated Action Detection (based on final thought for this step)
                    if action == self._last_action and args == self._last_args:
                        self._consecutive_same_action += 1
                    else:
                        self._last_action = action
                        self._last_args = args
                        self._consecutive_same_action = 0

                    # LOOP RESOLUTION: If we are stuck in the same state OR repeating actions
                    if self._consecutive_same_state >= 3 or self._consecutive_same_action >= 2:
                        trigger = "State Stall" if self._consecutive_same_state >= 3 else "Action Loop"
                        logger.warning(f"⚠️ [Loop Detection] {trigger} detected. Forcing Vision/Heuristic shift.")
                        if action != "vision":
                            action = "vision"
                            args = {
                                "reason": f"{trigger} detected. Page state or action is stuck. Re-evaluating via Vision-only scan."
                            }
                            thought = f"{thought} | Loop guard switched to vision re-check."
                            self._consecutive_same_action = 0
                    
                    logger.info(f"[{step_id}] 🧠 THOUGHT: {thought}")
                    logger.info(f"[{step_id}] 🎯 ACTION: {action}({args})")
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
                        logger.info(f"[{step_id}] ✅ GOAL REACHED (Self-Verified): {args.get('text')}")
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
                    resp = await self._execute_action(action, args, step_id, trace_id)

                    if str(getattr(resp, "status", "")) == "error":
                        err = str(getattr(resp, "error_details", "") or "Unknown planner execution error")
                        logger.warning(f"[{step_id}] ⚠️ Action failed: {action}({args}) -> {err}")
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
                    
                    # Optimistic Navigation: Get next state and carry on.
                    # The vision/perception update in the next loop iteration will naturally reveal success/failure.
                    state = await self._get_page_state(goal)
                    self._last_validation_context = self._build_validation_context(action, args, state)
                    
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
                    self._emit_worker_planner_update(
                        {
                            "phase": "error",
                            "step_id": step_id,
                            "step_num": step_num,
                            "error": str(e),
                        }
                    )
                    return self._fail(str(e), trace_id, step_id)

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
        url = await self._get_current_url()
        title = ""
        try:
            res = await self.runtime._call_cdp("Runtime.evaluate", {"expression": "JSON.stringify({title: document.title, w: window.innerWidth, h: window.innerHeight})", "returnByValue": True})
            info = json.loads(res.get("result", {}).get("value", "{}"))
            title = info.get("title", "")
            if info.get("w"): self._viewport = {"w": info["w"], "h": info["h"]}
        except: pass
        
        # 1. Parallel Data Acquisition
        # Dominates bottleneck: get DOM and take screenshot simultaneously
        dom_task = self.runtime.get_skeletal_dom()
        vis_task = self.runtime.capture_screenshot_to_file()
        
        results = await asyncio.gather(dom_task, vis_task)
        obs_data: Dict[str, Any] = results[0]
        screenshot_path: str = results[1]
        
        # 2. Parallel Analysis & Fusion
        # Uses PerceptionMerger to delegate to DomAnalyzer and ImageAnalyzer
        try:
            perception = await self.perception_merger.get_unified_state(
                dom_data=obs_data.get("nodes", []),
                image_data=screenshot_path,
                intent=goal or "Explore the page"
            )
        finally:
            # Cleanup screenshot
            if screenshot_path and os.path.exists(screenshot_path):
                try: os.remove(screenshot_path)
                except: pass
        
        logger.info(f"[Perception] Fused State: {len(perception['candidates'])} Candidates | Confidence: {perception['global_confidence']}")
        
        # Populate node map for action execution
        self._node_map = {}
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
                
                # Simplified entry for planner actions
                self._node_map[eid] = {
                    "id": eid,
                    "bbox": b,
                    "tag": c.get("semantic_role") or c.get("visual_role") or "",
                    "role": c.get("semantic_role") or c.get("visual_role") or "element",
                    "source": c.get("source", "DOM"),
                    "text": c.get("reasoning", "")
                }
        
        return {
            "url": url,
            "title": title,
            "candidates": perception["candidates"],
            "markers": obs_data.get("markers", []),
            "viewport": self._viewport,
            "total_nodes": obs_data.get("total_count", 0),
            "viewport_count": obs_data.get("viewport_count", 0),
            "global_trust": perception["global_confidence"]
        }

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
        
        system_prompt = BROWSER_AGENT_PROMPT.format(
            goal=goal, 
            plan=plan_str,
            current_step=current_step_str,
            total_nodes=state['total_nodes'],
            viewport_count=state['viewport_count']
        )
        user_prompt = f"### State:\nURL: {state['url']}\nTitle: {state['title']}\n"
        
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
        for c in state['candidates']:
            source = c.get("source", "DOM")
            label = c.get("element_id") or c.get("visual_role") or "unknown"
            text = c.get("reasoning", "")
            user_prompt += f"[{source}] {label}: '{text}'\n"

        if state.get('markers'):
            user_prompt += "\n### Landmarks (Informational):\n"
            for m in state['markers']:
                safe_text = str(m.get('text', '')).replace('"', "'")
                user_prompt += f"[{m['id']}] {m['kind']}: '{safe_text}'\n"
                
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

                return ToonResponse(
                    command_id=f"batch_{int(time.time())}",
                    component="planner",
                    action="action_batch",
                    trace_id=trace_id,
                    step_id=step_id,
                    status="success",
                    execution_time=0.1,
                    message=f"Batch executed with {executed} sub-steps.",
                )

            # Action Pacing: Wait 1.5s before every interactive action to allow SPA settling
            if action in ["click", "type", "scroll", "click_visual", "press_key"]:
                await asyncio.sleep(1.5)

            if action == "navigate":
                logger.info(f"[{step_id}] 🚀 Action: navigate -> {args.get('url')}")
                return await self.runtime.navigate(args.get("url"))

            elif action == "vision":
                logger.info(f"[{step_id}] 👁️ Action: vision (CDP Screenshot)")
                reason = args.get("reason", "Provide a general visual summary of the page.")
                obs = await self._get_vision_observation(reason, await self._get_current_url())
                self._last_vision_observation = obs if isinstance(obs, dict) else {}
                return ToonResponse(
                    command_id="vision",
                    component="planner",
                    action="vision",
                    trace_id=trace_id,
                    step_id=step_id,
                    status="success",
                    execution_time=1.5,
                    message=str(obs.get("prompt_view") or obs.get("summary") or ""),
                )

            elif action == "click_visual":
                resolved = self._resolve_click_visual_coords(args)
                if not resolved:
                    return self._fail("click_visual requires valid x/y or prior vision coordinates", trace_id, step_id)
                logger.info(
                    f"[{step_id}] 🖱️ Action: click_visual -> x:{resolved['x']}, y:{resolved['y']} (source={resolved['source']})"
                )
                tx = (float(resolved["x"]) / 1000.0) * self._viewport['w']
                ty = (float(resolved["y"]) / 1000.0) * self._viewport['h']
                return await self.runtime.click(x=tx, y=ty)

            elif action == "click":
                target = self._resolve_target_node(args.get("id"))
                if not target:
                    return self._fail(f"Node not found: {args.get('id')}", trace_id, step_id)
                logger.info(f"[{step_id}] 🖱️ Action: click -> node:{target.get('id')} | Role:{target.get('role')} | Label:\"{target.get('text')}\" | Bbox:{target.get('bbox')}")
                center = self._bbox_center(target)
                if center is None:
                    return self._fail(f"Node has invalid bbox: {target.get('id')}", trace_id, step_id)
                tx, ty = center
                logger.info(f"  └─ Resolved Coordinates: {round(tx,1)}, {round(ty,1)}")
                return await self.runtime.click(x=tx, y=ty)

            elif action == "type":
                node = self._resolve_target_node(args.get("id"))
                if not node:
                    return self._fail(f"Node not found: {args.get('id')}", trace_id, step_id)
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
                return await self.runtime.type_text(
                    text=str(args.get("text", "")),
                    x=float(tx),
                    y=float(ty),
                    press_enter=bool(args.get("press_enter", False)),
                    focus_before_type=True,
                    clear_existing=True,
                )

            elif action == "press_key":
                key = str(args.get("key") or "Enter")
                logger.info(f"[{step_id}] ⌨️ Action: press_key -> {key}")
                await self.runtime.press_key(key)
                return ToonResponse(
                    command_id="press_key",
                    component="planner",
                    action="press_key",
                    trace_id=trace_id,
                    step_id=step_id,
                    status="success",
                    execution_time=0.2,
                )

            elif action == "scroll":
                logger.info(f"[{step_id}] 📜 Action: scroll -> {args.get('direction')}")
                px = 600 if str(args.get("direction", "down")) == "down" else -600
                await self.runtime._call_cdp("Runtime.evaluate", {"expression": f"window.scrollBy(0, {px})"})
                await asyncio.sleep(1.0)
                return ToonResponse(command_id="scroll", component="planner", action="scroll", trace_id=trace_id, step_id=step_id, status="success", execution_time=1.1)

            elif action == "wait":
                seconds = float(args.get("seconds", 1) or 1)
                seconds = max(0.1, min(seconds, 8.0))
                logger.info(f"[{step_id}] ⏳ Action: wait -> {seconds}s")
                await asyncio.sleep(seconds)
                return ToonResponse(command_id="wait", component="planner", action="wait", trace_id=trace_id, step_id=step_id, status="success", execution_time=seconds)

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
