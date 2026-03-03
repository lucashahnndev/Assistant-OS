import os
import json
import logging
import asyncio
import time
import re
from typing import Dict, Any, List, Optional, Union

from .schemas import ToonResponse, EvidencePack, BBox
from .runtime import BrowserRuntime

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

    def _extract_url(self, goal: str) -> str:
        goal_lower = goal.lower()
        if "youtube" in goal_lower: return "https://www.youtube.com"
        if "spotify" in goal_lower: return "https://www.spotify.com"
        if "github" in goal_lower: return "https://www.github.com"
        if "google" in goal_lower: return "https://www.google.com"
        match = re.search(r"https?://[^\s,]+", goal)
        return match.group(0) if match else "https://www.google.com"

    async def run_to_goal(self, goal: str, playback_service: Any = None, run_id: str = "default", session_id: str = "default") -> ToonResponse:
        self._playback_service = playback_service
        self._playback_run_id = run_id
        self._playback_session_id = session_id
        self._playback_step_count = 0

        logger.info(f"\n{'='*60}\n🚀 STARTING BROWSER GOAL: {goal}\n{'='*60}")
        trace_id = self.runtime._trace_id
        history: List[Dict[str, Any]] = []
        self._last_url = await self._get_current_url()
        
        # Initialize Master Plan
        if not self._plan:
            await self._generate_master_plan(goal)
        
        for step_num in range(1, self.max_steps + 1):
            step_id = f"step_{step_num}"
            logger.info(f"\n--- [ {step_id.upper()} ] ---")
            
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
                    logger.info(f"[{step_id}] ✅ GOAL REACHED: {args.get('text')}")
                    # Record final frame before finishing
                    await self._record_playback_frame(step_num, "answer", args)
                    return ToonResponse(
                        command_id="finish", component="planner", action="wait", trace_id=trace_id, step_id=step_id, status="success",
                        execution_time=0.1, message=args.get("text")
                    )

                # EXECUTION PHASE
                resp = await self._execute_action(action, args, step_id, trace_id)
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

    async def _get_page_state(self) -> Dict[str, Any]:
        """Captures skeletal DOM state restricted to the viewport with extreme logging."""
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

    async def _get_vision_context(self, goal: str, state: Dict[str, Any]) -> str:
        """Takes a CDP screenshot and returns a descriptive visual analysis."""
        path = await self.runtime.capture_screenshot_to_file()
        prompt = (
            f"You are the visual eyes of a browser agent. Goal: {goal}. URL: {state['url']}. "
            "Describe exactly what you see on screen. Identify items the DOM might have missed (titles, status indicators). "
            "If asked for coordinates, provide them as X, Y (0-1000). Be concise."
        )
        try:
            result = await asyncio.to_thread(self.llm_manager.analyze_image, image_path=path, prompt=prompt)
            logger.info(f"[Vision] Observer Feedback: {str(result)[:200]}...")
            return str(result)
        except Exception as e:
            return f"Vision fallback failed: {e}"
        finally:
            if path and os.path.exists(str(path)):
                try: os.remove(str(path))
                except: pass

    def _reconcile_plan_by_state(self, state: Dict[str, Any]):
        """Heuristic check: if URL changed significantly, we likely finished a step."""
        url = state['url'].lower()
        plan_step = self._plan[self._current_step_idx].lower() if self._current_step_idx < len(self._plan) else ""
        
        # Mapping URLs to typical plan keywords
        if "/results" in url or "search_query" in url:
            if "search" in plan_step or "pesquisar" in plan_step or "execute a search" in plan_step:
                self._current_step_idx += 1
                logger.info(f"⚡ [Auto-Reconcile] Search detected in URL. Advancing to step {self._current_step_idx + 1}")
        
        elif "/watch" in url:
            # If we are on a watch page, we definitely finished searching and clicking
            # Find the step about clicking or identifying the video
            while self._current_step_idx < len(self._plan) - 1:
                current_p = self._plan[self._current_step_idx].lower()
                if any(k in current_p for k in ["click", "search", "pesquisar", "identify", "locate"]):
                    self._current_step_idx += 1
                else:
                    break
            logger.info(f"⚡ [Auto-Reconcile] URL is /watch. Synchronized to step {self._current_step_idx + 1}")

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
                logger.critical("🛑 [ABORT] Too many consecutive parse failures. Aborting task to prevent loop.")
                raise Exception(f"PLANNER_OUTPUT_INVALID: Model failed to produce valid JSON twice. Raw: {raw_text[:200]}...")
                
            return {"action": "wait", "thought": f"Parse error ({e}). Retrying..."}

    async def _execute_action(self, action: str, args: Dict[str, Any], step_id: str, trace_id: str) -> ToonResponse:
        try:
            # Action Pacing: Wait 1.5s before every interactive action to allow SPA settling
            if action in ["click", "type", "scroll", "click_visual"]:
                await asyncio.sleep(1.5)

            if action == "navigate":
                logger.info(f"[{step_id}] 🚀 Action: navigate -> {args.get('url')}")
                return await self.runtime.navigate(args.get("url"))

            elif action == "vision":
                logger.info(f"[{step_id}] 👁️ Action: vision (CDP Screenshot)")
                obs = await self._get_vision_context("", await self._get_page_state())
                return ToonResponse(command_id="vision", component="planner", action="vision", trace_id=trace_id, step_id=step_id, status="success", execution_time=1.5, message=obs)

            elif action == "click_visual":
                logger.info(f"[{step_id}] 🖱️ Action: click_visual -> x:{args.get('x')}, y:{args.get('y')}")
                tx = (float(args.get('x', 0)) / 1000.0) * self._viewport['w']
                ty = (float(args.get('y', 0)) / 1000.0) * self._viewport['h']
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
                
                await self.runtime.click(x=tx, y=ty)
                await asyncio.sleep(0.5)
                # Clear field using CDP keyboard events
                await self.runtime._call_cdp("Input.dispatchKeyEvent", {"type": "keyDown", "modifiers": 2, "windowsVirtualKeyCode": 65, "key": "a"}) # Ctrl+A
                await self.runtime._call_cdp("Input.dispatchKeyEvent", {"type": "keyUp", "modifiers": 2, "windowsVirtualKeyCode": 65, "key": "a"})
                await self.runtime._call_cdp("Input.dispatchKeyEvent", {"type": "keyDown", "windowsVirtualKeyCode": 8, "key": "Backspace"}) # Backspace
                await self.runtime._call_cdp("Input.dispatchKeyEvent", {"type": "keyUp", "windowsVirtualKeyCode": 8, "key": "Backspace"})
                
                for c in str(args.get("text", "")):
                    await self.runtime._call_cdp("Input.dispatchKeyEvent", {"type": "keyDown", "text": c})
                    await self.runtime._call_cdp("Input.dispatchKeyEvent", {"type": "keyUp", "text": c})
                if args.get("press_enter"):
                    await self.runtime._call_cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "windowsVirtualKeyCode": 13})
                await self.runtime._wait_for_load()
                return ToonResponse(command_id="type", component="planner", action="type", trace_id=trace_id, step_id=step_id, status="success", execution_time=1.0)

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
        # Heuristic fix for common LLM syntax error: "thought "Eu já..." (missing colon)
        fixed = re.sub(r'\"thought\"\s+\"', '"thought": "', t)
        fixed = re.sub(r'\"thought\"\s+:', '"thought":?', fixed) # enforce standard spacing
        fixed = re.sub(r'\"thought\":?\s+\"', '"thought": "', fixed)
        
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
        except Exception as e:
            logger.error(f"Failed to record playback frame: {e}")
