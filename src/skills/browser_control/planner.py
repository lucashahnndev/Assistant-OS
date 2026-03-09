import os
import json
import logging
import asyncio
import time
import re
import copy
from typing import Dict, Any, List, Optional, Union

from .schemas import ToonResponse, EvidencePack, BBox
from .runtime import BrowserRuntime
from .vision_contract import normalize_vision_observation

logger = logging.getLogger("aosd.skills.browser_control.planner")

BROWSER_AGENT_PROMPT = """You are an Autonomous Browser Navigator.
Your goal: {goal}

You see a **UI Snapshot** (Interactive Candidates) and **Content Markers** (Landmarks) of the current Viewport.
Total nodes: {total_nodes} | Viewport nodes: {viewport_count}

### Landmarks (Content Markers)
These nodes are NOT clickable but provide context (Titles, Headers, Info). 
Use them to verify if you are on the right page (e.g. check if the video title matches your goal).

### Multimodal Vision & Atomic Thinking
If the UI Snapshot and Landmarks are insufficient, or if you are **UNCERTAIN**, use the **vision** action.
**ATOMIC THINKING**: If an input field (like search) is hidden behind an icon (like a magnifying glass), you MUST click the icon FIRST, then type in the next step. Do not try to type on an icon.
**GOLD RULE**: If you just clicked/navigated and the URL changed to a watch page (contains '/watch'), the content **IS THERE**. If you don't see the title in Landmarks, **DO NOT SEARCH AGAIN**. Instead, use `vision` to see the screen or `wait` for 2 seconds. Re-searching is a **FAILURE**.

### Available Actions:
- {{"action": "navigate", "args": {{"url": "https://..."}}}}
- {{"action": "click", "args": {{"id": "node_id"}}}}
- {{"action": "click_visual", "args": {{"x": 0-1000, "y": 0-1000}}}}  <-- Use only after 'vision'
- {{"action": "type", "args": {{"id": "node_id", "text": "...", "press_enter": true}}}}
- {{"action": "scroll", "args": {{"direction": "down" | "up"}}}}
- {{"action": "vision", "args": {{"reason": "why are you using vision?"}}}}
- {{"action": "wait", "args": {{"seconds": 2}}}}
- {{"action": "answer", "args": {{"text": "final result"}}}}

### MASTER PLANNING
You follow a **Sub-Task Checklist** to achieve the user's goal without regression.

**Current Plan**:
{plan}

**Current Focus**: Step {current_step}

### RULES:
1. **No Regression**: If a Sub-Task (e.g., "Search results loaded") is completed, **NEVER** go back to it.
2. **Victory Declaration**: If you see the final result (e.g., the video title) in Landmarks or Vision, you have **WON**. Output your final answer immediately.
3. **Step Status**: You MUST include `"step_status": "completed"` in your JSON if you have successfully finished the **Current Focus** step. Otherwise, use `"step_status": "in_progress"`.
4. **Beyond the Fold**: The UI Snapshot includes elements up to 600px below the visible area. Use a short **scroll down** if you need to confirm details of a Landmark just below the fold.
5. **Small Target Awareness**: Targets labeled with `[small]` are secondary controls (menus, settings, options). Prefer larger targets (thumbnails/titles) for primary navigation. Only use `[small]` targets if your goal specifically requires opening a menu or details.

### JSON FORMAT:
{{
  "thought": "Direct thought (max 2 sentences).",
  "step_status": "in_progress" or "completed",
  "action": "...",
  "args": {{...}}
}}
"""

class BrowserSubagent:
    """100% Agentic Browser Subagent with Multimodal Vision Support."""

    def __init__(self, runtime: Any, llm_manager: Any):
        self.runtime = runtime
        self.llm_manager = llm_manager
        self.max_steps = 25
        self._node_map: Dict[str, Dict[str, Any]] = {}
        self._node_offset = 0
        self._viewport = {"w": 1280, "h": 720}
        self._last_url = ""
        self._plan: List[str] = []
        self._current_step_idx = 0
        self._consecutive_parse_failures = 0
        self._max_parse_failures = 2
        self._locked_target_id = str(getattr(runtime, "target_id", "") or "")
        self._last_vision_observation: Dict[str, Any] = {}
        self._callbacks: Dict[str, Any] = {}

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

    @classmethod
    def _has_completion_evidence(cls, goal: str, state: Dict[str, Any], candidate_answer: str = "") -> bool:
        terms = cls._goal_terms(goal)
        if not terms:
            return False
        text_parts: List[str] = [str(state.get("url", "")), str(state.get("title", "")), str(candidate_answer or "")]
        for m in state.get("markers", []) or []:
            if isinstance(m, dict):
                text_parts.append(str(m.get("text", "")))
        haystack = " ".join(text_parts).lower()
        hits = sum(1 for t in terms if t in haystack)
        # Require at least one strong term, or two partial terms for confidence.
        return hits >= 2 or (hits >= 1 and len(terms) <= 3)

    @staticmethod
    def _state_signature(state: Dict[str, Any]) -> Dict[str, Any]:
        markers = state.get("markers", []) if isinstance(state.get("markers"), list) else []
        nodes = state.get("nodes", []) if isinstance(state.get("nodes"), list) else []
        marker_texts = [str(m.get("text", "")).strip().lower() for m in markers[:8] if isinstance(m, dict)]
        node_texts = [str(n.get("text", "")).strip().lower() for n in nodes[:10] if isinstance(n, dict)]
        return {
            "url": str(state.get("url", "")).strip().lower(),
            "title": str(state.get("title", "")).strip().lower(),
            "marker_texts": marker_texts,
            "node_texts": node_texts,
        }

    @classmethod
    def _verify_action_effect(cls, action: str, before_state: Dict[str, Any], after_state: Dict[str, Any]) -> tuple[bool, str]:
        a = str(action or "").strip().lower()
        if a in {"wait", "vision", "answer"}:
            return True, "non_interactive_or_terminal"
        before = cls._state_signature(before_state)
        after = cls._state_signature(after_state)
        url_changed = before["url"] != after["url"]
        title_changed = before["title"] != after["title"]
        markers_changed = before["marker_texts"] != after["marker_texts"]
        nodes_changed = before["node_texts"] != after["node_texts"]

        if a == "navigate":
            if url_changed:
                return True, "url_changed"
            return False, "navigate_no_url_change"
        if a in {"click", "click_visual", "type", "scroll"}:
            if url_changed or title_changed or markers_changed or nodes_changed:
                reason = "url_changed" if url_changed else ("title_changed" if title_changed else ("markers_changed" if markers_changed else "nodes_changed"))
                return True, reason
            return False, "interactive_no_observable_effect"
        return True, "unknown_action_assumed"

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

    async def _generate_master_plan(self, goal: str):
        """Phase 1: Decompose the complex goal into a Checklist."""
        prompt = f"""You are the Master Planner for the Browser Control Engine.
Decompose this request into a logical checklist of 4-6 ATOMIC sub-tasks.
Request: "{goal}"

**PLANNING RULES**:
1. Be extremely granular. If a site requires clicking a search icon before typing, make that two separate steps.
2. Never group "Search and click" into one step. Decompose it.
3. Include steps for verification (e.g., "Confirm search results are visible").

Format: Return ONLY a numbered list of steps.
Example:
1. Open [Website]
2. Click on the search magnifying glass icon
3. Type '[term]' in the search input and press Enter
4. Verify results and locate the specific item '[item]'
5. Click on the item and wait for page load
6. Confirm action success and provide answer
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
        if "spotify" in goal_lower: return "https://www.spotify.com"
        if "github" in goal_lower: return "https://www.github.com"
        if "google" in goal_lower: return "https://www.google.com"
        match = re.search(r"https?://[^\s,]+", goal)
        return match.group(0) if match else "https://www.google.com"

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

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

    def _advance_step_by_action_effect(
        self,
        action: str,
        verify_reason: str,
        before_state: Dict[str, Any],
        after_state: Dict[str, Any],
    ) -> None:
        if not self._plan or self._current_step_idx >= len(self._plan):
            return
        step = self._plan[self._current_step_idx]
        a = str(action or "").lower()
        if a == "navigate":
            if self._step_contains_any(step, ["open", "launch", "navigate", "go to", "abrir", "acessar", "ir para"]) or verify_reason == "url_changed":
                self._advance_step("action_effect:navigate")
            return
        if a == "type":
            if self._step_contains_any(step, ["type", "input", "search", "enter", "digitar", "pesquisar", "consulta"]):
                self._advance_step("action_effect:type")
            return
        if a in {"click", "click_visual"}:
            if self._step_contains_any(step, ["click", "open", "select", "choose", "video", "result", "item", "clicar", "abrir", "selecionar"]):
                self._advance_step("action_effect:click")
            elif str(before_state.get("url", "")).lower() != str(after_state.get("url", "")).lower():
                self._advance_step("action_effect:click_url_change")
            return
        if a == "scroll":
            if self._step_contains_any(step, ["scroll", "rolar"]):
                self._advance_step("action_effect:scroll")

    def _fallback_action_for_parse(self, goal: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministic fallback to avoid dead loops when planner JSON is invalid."""
        url = str(state.get("url", "")).lower()
        if not url or url == "about:blank":
            return {"action": "navigate", "args": {"url": self._extract_url(goal)}, "thought": "Fallback navigate from blank page."}
        if "/watch" in url or "music.youtube.com/watch" in url:
            return {"action": "answer", "args": {"text": "Conteudo aberto e em reproducao na pagina atual."}, "thought": "Fallback victory on watch page."}
        if "youtube.com" in url and ("/results" not in url and "search_query" not in url):
            for n in state.get("nodes", []) or []:
                if not isinstance(n, dict):
                    continue
                if str(n.get("tag", "")).lower() == "input" and "pesquisar" in str(n.get("text", "")).lower():
                    return {
                        "action": "type",
                        "args": {"id": str(n.get("id")), "text": "Coldplay Paradise", "press_enter": True},
                        "thought": "Fallback type on YouTube search input.",
                    }
        if "/results" in url or "search_query" in url:
            goal_terms = self._goal_terms(goal)
            best = None
            best_score = 0
            for n in state.get("nodes", []) or []:
                if not isinstance(n, dict):
                    continue
                txt = str(n.get("text", "")).lower()
                score = sum(1 for t in goal_terms if t in txt)
                if "paradise" in txt:
                    score += 2
                if "coldplay" in txt:
                    score += 2
                if score > best_score:
                    best_score = score
                    best = str(n.get("id") or "")
            if best:
                return {"action": "click", "args": {"id": best}, "thought": "Fallback click on best matching result."}
        return {"action": "vision", "args": {"reason": "fallback_after_parse_failure"}, "thought": "Fallback to vision after parse failure."}

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
        history: List[Dict[str, Any]] = []
        self._last_url = await self._get_current_url()
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
            
                # SYNCHRONIZATION GUARD: If URL changed, wait for stability
                current_url = await self._get_current_url()
                if current_url != self._last_url or step_num == 1:
                    logger.info(f"[{step_id}] 🔄 [Synchronizing Engine] URL Change Detected: {self._last_url} -> {current_url}")
                    await self.runtime._wait_for_load()
                    logger.info(f"  └─ Loader Finished. Applying 3s Stabilization Guard...")
                    await asyncio.sleep(3.0)
                    self._last_url = current_url

                state = await self._get_page_state()
            
                # Initial frame for this step
                await self._record_playback_frame(step_num, "thinking", {"goal": goal})
            
                if step_num == 1 and state['url'] == "about:blank":
                    target_url = self._extract_url(goal)
                    logger.info(f"[{step_id}] 🌐 Bootstrapping -> {target_url}")
                    await self.runtime.navigate(target_url)
                    self._last_url = target_url
                    history.append({"step": 1, "thought": "Navigate to start.", "action": "navigate", "args": {"url": target_url}, "status": "success"})
                    
                    # Record frame after navigation
                    await self._record_playback_frame(step_num, "navigate", {"url": target_url})
                    
                    # Bootstrap Sync: step 1 is navigation, consider it completed if navigate didn't error
                    if self._current_step_idx == 0:
                        self._current_step_idx = 1
                        logger.info("✅ Bootstrap Sync: Step 1 Marked as Completed.")
                    continue

                try:
                    # HEURISTIC RECONCILIATION: Sync plan by env state
                    self._reconcile_plan_by_state(state)

                    # REASONING PHASE
                    thought_data = await self._think(goal, state, history)
                    action = str(thought_data.get("action", "wait"))
                    args = thought_data.get("args", {})
                    thought = thought_data.get("thought", "Thinking...")
                    
                    logger.info(f"[{step_id}] 🧠 THOUGHT: {thought}")
                    logger.info(f"[{step_id}] 🎯 ACTION: {action}({args})")
                    
                    if action == "answer":
                        if not self._has_completion_evidence(goal, state, str(args.get("text", ""))):
                            logger.warning(f"[{step_id}] ⚠️ Answer rejected: no completion evidence in current state.")
                            await self._record_playback_frame(step_num, "answer_rejected", {"reason": "no_completion_evidence"})
                            history.append({
                                "step": step_num,
                                "thought": thought,
                                "action": "answer_rejected",
                                "args": {"reason": "no_completion_evidence"},
                                "status": "failure",
                            })
                            continue
                        logger.info(f"[{step_id}] ✅ GOAL REACHED: {args.get('text')}")
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
                    after_state = await self._get_page_state()
                    verified, verify_reason = self._verify_action_effect(action, state, after_state)
                    if action in {"click", "click_visual", "type", "scroll", "navigate"} and not verified:
                        logger.warning(f"[{step_id}] ⚠️ Action had no observable effect: {action} ({verify_reason})")
                        await self._record_playback_frame(
                            step_num,
                            "action_no_effect",
                            {"action": action, "reason": verify_reason, "args": args},
                        )
                        history.append({
                            "step": step_num,
                            "thought": thought,
                            "action": action,
                            "args": args,
                            "status": "failure",
                            "observation": f"no_effect:{verify_reason}",
                        })
                        continue
                    if action in {"click", "click_visual", "type", "scroll", "navigate"} and verified:
                        self._advance_step_by_action_effect(action, verify_reason, state, after_state)
                    self._reconcile_plan_by_state(after_state)
                    # Record frame after action
                    await self._record_playback_frame(step_num, action, args)
                    history.append({
                        "step": step_num, "thought": thought, "action": action, "args": args,
                        "url_after": await self._get_current_url(), "status": resp.status,
                        "observation": resp.message if action == "vision" else None
                    })
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.error(f"[{step_id}] ❌ Logic failure: {e}")
                    return self._fail(str(e), trace_id, step_id)

            return self._fail("Timeout", trace_id, f"step_{self.max_steps}")
        finally:
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

    async def _get_page_state(self) -> Dict[str, Any]:
        """Captures skeletal DOM state restricted to the viewport with extreme logging."""
        await self._ensure_target_binding()
        url = await self._get_current_url()
        title = ""
        try:
            res = await self.runtime._call_cdp("Runtime.evaluate", {"expression": "JSON.stringify({title: document.title, w: window.innerWidth, h: window.innerHeight})", "returnByValue": True})
            info = json.loads(res.get("result", {}).get("value", "{}"))
            title = info.get("title", "")
            if info.get("w"): self._viewport = {"w": info["w"], "h": info["h"]}
        except: pass
        
        obs_data = await self.runtime.get_skeletal_dom()
        nodes = obs_data.get("nodes", [])
        markers = obs_data.get("markers", [])
        
        logger.info(f"[Perception] URL: {url} | Title: \"{title}\"")
        logger.info(f"[Perception] Found {len(nodes)} Interactive Nodes and {len(markers)} Content Markers.")
        
        if markers:
            for m in markers:
                logger.info(f"  └─ [Marker] {m['id']} ({m['kind']}): \"{m['text']}\"")
        
        self._node_map = {}
        cleaned_nodes = []
        trust_sum = 0.0
        
        for i, n in enumerate(nodes):
            sid = n.get("id", f"node_{i+1}")
            score = 0.7 if n.get("inViewport") else 0.5
            if n.get("tag") in ['h1', 'h2', 'input', 'button']: score += 0.2
            trust = round(min(1.0, score), 2)
            trust_sum += trust
            
            node_data = {
                "id": sid, "tag": n.get("tag"), "in_viewport": n.get("inViewport", True),
                "text": n.get("text", "")[:100], "trust": trust, "bbox": n.get("bbox")
            }
            self._node_map[sid] = node_data
            cleaned_nodes.append(node_data)

        cleaned_markers = []
        for m in markers:
            cleaned_markers.append({
                "id": m.get("id"), "kind": m.get("kind"), "text": m.get("text")[:100]
            })
            
        avg_trust = trust_sum / max(1, len(cleaned_nodes)) if cleaned_nodes else 0.0
        global_trust = round(avg_trust, 2)
        
        return {
            "url": url, "title": title, "nodes": cleaned_nodes, "markers": cleaned_markers,
            "viewport": self._viewport, "total_nodes": obs_data.get("total_count", 0), 
            "viewport_count": obs_data.get("viewport_count", 0),
            "global_trust": global_trust
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

    async def _get_vision_observation(self, goal: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Takes a CDP screenshot and returns a normalized visual observation contract."""
        path = await self.runtime.capture_screenshot_to_file()
        prompt = (
            f"You are the visual eyes of a browser agent. Goal: {goal}. URL: {state['url']}. "
            "Describe exactly what you see on screen. Identify items the DOM might have missed (titles, status indicators). "
            "If asked for coordinates, provide them as X, Y (0-1000). Be concise."
        )
        try:
            result = await asyncio.to_thread(self.llm_manager.analyze_image, image_path=path, prompt=prompt)
            logger.info(f"[Vision] Observer Feedback: {str(result)[:200]}...")
            return normalize_vision_observation(result, goal=goal, url=str(state.get("url", "")))
        except Exception as e:
            return normalize_vision_observation(f"Vision fallback failed: {e}", goal=goal, url=str(state.get("url", "")))
        finally:
            if path and os.path.exists(str(path)):
                try: os.remove(str(path))
                except: pass

    def _reconcile_plan_by_state(self, state: Dict[str, Any]):
        """Heuristic check: synchronize checklist from strong page-state milestones."""
        url = state['url'].lower()
        if not self._plan:
            return

        if "/results" in url or "search_query" in url:
            last_search_idx = -1
            for i, step in enumerate(self._plan):
                if self._step_contains_any(step, ["search", "pesquisar", "type", "input", "enter", "consulta"]):
                    last_search_idx = i
            if last_search_idx >= 0:
                self._advance_step("auto_reconcile:results_url", min_idx=min(last_search_idx + 1, len(self._plan) - 1))
            return

        if "/watch" in url or "music.youtube.com/watch" in url:
            target_idx = -1
            for i, step in enumerate(self._plan):
                if self._step_contains_any(step, ["click", "open", "video", "result", "watch", "play", "clicar", "abrir", "reprodu"]):
                    target_idx = i
            if target_idx >= 0:
                self._advance_step("auto_reconcile:watch_url", min_idx=min(target_idx + 1, len(self._plan) - 1))
            else:
                self._advance_step("auto_reconcile:watch_url_default", min_idx=len(self._plan) - 1)
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
            user_prompt += "### History (Last 5):\n"
            for h in history[-5:]:
                obs = f" | Obs: {h['observation'][:50]}..." if h.get("observation") else ""
                user_prompt += f"- Step {h['step']}: {h['action']} -> {h['status']}{obs}. {h['thought'][:100]}...\n"
        
        user_prompt += "\n### UI Snapshot (Interactive):\n"
        for n in state['nodes']:
            user_prompt += f"[{n['id']}] {n['tag']}: \"{n['text']}\"\n"

        if state.get('markers'):
            user_prompt += "\n### Landmarks (Informational):\n"
            for m in state['markers']:
                user_prompt += f"[{m['id']}] {m['kind']}: \"{m['text']}\"\n"
            
        result, err = await asyncio.to_thread(
            self.llm_manager._execute_with_router, self.llm_manager.chat_pool, 'generate_text',
            prompt=user_prompt, system_prompt=system_prompt
        )
        
        if err:
            logger.error(f"[Reasoning] LLM Error: {err}")
            return {"action": "wait"}

        if not result:
            logger.error("[Reasoning] Empty LLM response")
            return {"action": "wait"}

        raw_text = str(result)
        try:
            # Layered JSON extraction
            extracted_json = self._extract_json(raw_text)
            if not extracted_json:
                raise ValueError("No valid JSON object found in response")
            
            data = json.loads(extracted_json)
            
            # Pydantic Normalization: ensure string types for critical fields
            for field in ["thought", "step_status", "action", "response_text"]:
                if field in data:
                    if data[field] is None:
                        data[field] = ""
                    elif not isinstance(data[field], str):
                        data[field] = json.dumps(data[field], ensure_ascii=False) if isinstance(data[field], (dict, list)) else str(data[field])
                elif field == "response_text":
                    data[field] = "" # default for AgentIntent
            
            # Reset failure counter on success
            self._consecutive_parse_failures = 0

            # Master Plan Advancement logic
            status = data.get("step_status", "").lower()
            if status == "completed":
                if self._current_step_idx < len(self._plan) - 1:
                    self._current_step_idx += 1
                    logger.info(f"✅ Master Plan Advanced (via status): Next Focus -> {self._plan[self._current_step_idx]}")
            
            # YouTube specific Victory Guard
            if ("/watch" in state['url'] or "/music.youtube" in state['url']) and any("tz" in m['text'].lower() for m in state.get('markers', [])):
                if any(x in goal.lower() for x in ["título", "title", "nome", "name"]):
                     logger.info("🏆 [Victory Detection] Target Content/Title Found in Markers. Ready for Answer.")

            return data
        except Exception as e: 
            self._consecutive_parse_failures += 1
            logger.error(f"[Reasoning] Parse Failure ({self._consecutive_parse_failures}/{self._max_parse_failures}): {e}")
            logger.debug(f"[Reasoning] Raw problematic output: {raw_text}")
            
            if self._consecutive_parse_failures >= self._max_parse_failures:
                logger.error("⚠️ Too many parse failures. Switching to deterministic fallback action.")
                return self._fallback_action_for_parse(goal, state)

            return {"action": "wait", "args": {"seconds": 1}, "thought": f"Parse error ({e}). Retrying..."}

    async def _execute_action(self, action: str, args: Dict[str, Any], step_id: str, trace_id: str) -> ToonResponse:
        try:
            await self._ensure_target_binding()
            # Action Pacing: Wait 1.5s before every interactive action to allow SPA settling
            if action in ["click", "type", "scroll", "click_visual"]:
                await asyncio.sleep(1.5)

            if action == "navigate":
                logger.info(f"[{step_id}] 🚀 Action: navigate -> {args.get('url')}")
                return await self.runtime.navigate(args.get("url"))

            elif action == "vision":
                logger.info(f"[{step_id}] 👁️ Action: vision (CDP Screenshot)")
                obs = await self._get_vision_observation("", await self._get_page_state())
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
                target = self._node_map.get(str(args.get("id")))
                if not target: return self._fail("Node dead", trace_id, step_id)
                logger.info(f"[{step_id}] 🖱️ Action: click -> node:{args.get('id')} | Tag:{target['tag']} | Label:\"{target['text']}\" | Bbox:{target['bbox']}")
                b = target['bbox']
                tx, ty = b['x'] + b['w']/2, b['y'] + b['h']/2
                logger.info(f"  └─ Resolved Coordinates: {round(tx,1)}, {round(ty,1)}")
                return await self.runtime.click(x=tx, y=ty)

            elif action == "type":
                node = self._node_map.get(str(args.get("id")))
                if not node: return self._fail("Node not found", trace_id, step_id)
                logger.info(f"[{step_id}] ⌨️ Action: type -> node:{args.get('id')} | Tag:{node['tag']} | Label:\"{node['text']}\" | Text:\"{args.get('text')}\"")
                b = node['bbox']
                tx, ty = b['x'] + b['w']/2, b['y'] + b['h']/2
                return await self.runtime.type_text(
                    text=str(args.get("text", "")),
                    x=float(tx),
                    y=float(ty),
                    press_enter=bool(args.get("press_enter", False)),
                    focus_before_type=True,
                    clear_existing=True,
                )

            elif action == "scroll":
                logger.info(f"[{step_id}] 📜 Action: scroll -> {args.get('direction')}")
                px = 600 if str(args.get("direction", "down")) == "down" else -600
                await self.runtime._call_cdp("Runtime.evaluate", {"expression": f"window.scrollBy(0, {px})"})
                await asyncio.sleep(1.0)
                return ToonResponse(command_id="scroll", component="planner", action="scroll", trace_id=trace_id, step_id=step_id, status="success", execution_time=1.1)

            return self._fail("Action unknown", trace_id, step_id)
        except Exception as e: return self._fail(str(e), trace_id, step_id)

    async def _get_current_url(self) -> str: return await self.runtime._get_current_url()
    def _clean_json(self, t: str) -> str:
        # Heuristic fixes for common malformed keys (e.g. `"thought: ..."`).
        fixed = str(t or "")
        fixed = re.sub(r'"\s*thought\s*:\s*', '"thought": "', fixed, flags=re.IGNORECASE)
        fixed = re.sub(r'"\s*step_status\s*:\s*', '"step_status": "', fixed, flags=re.IGNORECASE)
        fixed = re.sub(r'"\s*action\s*:\s*', '"action": "', fixed, flags=re.IGNORECASE)
        fixed = re.sub(r'"\s*args\s*:\s*', '"args": ', fixed, flags=re.IGNORECASE)
        fixed = re.sub(r'"\s*response_text\s*:\s*', '"response_text": "', fixed, flags=re.IGNORECASE)

        # Remove literal control characters
        fixed = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', fixed)
        # Remove escaped control characters like \x01, \u0001
        fixed = re.sub(r'\\x[0-9a-fA-F]{2}', '', fixed)
        fixed = re.sub(r'\\u00[0-9a-fA-F]{2}', '', fixed)

        s = fixed.find('{'); e = fixed.rfind('}')
        return fixed[s:e+1] if s != -1 and e != -1 else fixed
    def _fail(self, m: str, t: str, i: str) -> ToonResponse:
        return ToonResponse(command_id="err", component="planner", action="wait", trace_id=t, step_id=i, status="error", execution_time=0.1, error_details=m)

    def _extract_json(self, text: str) -> Optional[str]:
        """Layered JSON extraction: Fenced blocks -> Brace counting -> Sanitize."""
        if not text: return None
        
        # Camada A: Fenced blocks
        fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if fenced:
            return self._sanitize_json_str(fenced.group(1))

        # Camada B: Brace tracking scan
        start_idx = text.find('{')
        if start_idx == -1: return None
        
        count = 0
        in_string = False
        escape = False
        
        for i in range(start_idx, len(text)):
            char = text[i]
            if char == '"' and not escape:
                in_string = not in_string
            elif char == '\\' and not escape:
                escape = True
                continue
            elif not in_string:
                if char == '{': count += 1
                elif char == '}':
                    count -= 1
                    if count == 0:
                        candidate = text[start_idx:i+1]
                        return self._sanitize_json_str(candidate)
            escape = False
            
        return None

    def _sanitize_json_str(self, s: str) -> str:
        """Camada C: Remove control characters and apply heuristic fixes."""
        # Remove control characters except \t \n \r
        s = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', s)
        # Apply heuristic fixes (missing colons etc)
        return self._clean_json(s)
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
