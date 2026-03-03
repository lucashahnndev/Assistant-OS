import asyncio
import logging
from typing import List, Dict, Any, Optional, Union
from ..base import SkillBase

logger = logging.getLogger("aosd.skills.browser_control")

class BrowserControlSkill(SkillBase):
    def __init__(self, kernel: Any, config: Dict[str, Any]):
        self.kernel = kernel
        self._config = config
        self._runtime: Optional[Any] = None
        self._subagent: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def name(self) -> str:
        return "browser_control"

    @property
    def actions(self) -> List[str]:
        return ["run", "step", "close"]

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        return [
            {
                "pattern": r"(?i)(?:abr[aei]|open|launch|inicie?)\s+(?:o\s+)?(?:navegador|browser|chrome|google\s+chrome)",
                "action_id": "browser.control.run",
                "handler": lambda m: {"goal": m.string},
            },
        ]

    def get_keywords(self) -> List[str]:
        return [
            "navegador", "browser", "chrome", "abra o google",
            "abra o navegador", "open browser", "clique", "click",
            "navegar", "navigate", "browser control",
        ]

    async def _ensure_runtime(self, headless: bool = False, muted: bool = False):
        from .runtime import BrowserRuntime
        from .planner import BrowserSubagent
        current_loop = asyncio.get_running_loop()

        # Re-init if loop changed or launch options differ
        if self._runtime and self._loop != current_loop:
            logger.info("Event loop changed, re-initializing runtime")
            self._runtime = None
            self._subagent = None

        if not self._runtime:
            if not self.kernel:
                raise RuntimeError("Kernel not initialized in BrowserControlSkill")
            self._loop = current_loop
            self._runtime = BrowserRuntime(headless=headless, muted=muted)
            await self._runtime.launch()
            self._subagent = BrowserSubagent(self._runtime, self.kernel.llm_manager)

    def _run_sync(self, coro):
        """Helper to run a coroutine from a synchronous context, 
        even if an event loop is already running in the current thread."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # We are in an async context. We must run in a separate thread to block.
                import threading
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(lambda: asyncio.run(coro)).result()
            return loop.run_until_complete(coro)
        except RuntimeError:
            # No loop running in this thread
            return asyncio.run(coro)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        
        action = action_id.split(".")[-1]

        if action == "run":
            goal = (
                params.get("goal")
                or params.get("instruction")
                or params.get("query")
                or context.get("user_input")
                or context.get("prompt")
                or ""
            )
            # Optional launch params — agent can pass these or they default to sane values
            headless = bool(params.get("headless", self._config.get("headless", False)))
            muted = bool(params.get("muted", False))
            logger.info(f"Resolved goal for 'run': '{goal}' (from params keys: {list(params.keys())})")
            return self._run_sync(self.run_goal(goal, headless=headless, muted=muted, context=context))
        elif action == "step":
            instruction = (
                params.get("instruction")
                or params.get("goal")
                or params.get("query")
                or context.get("user_input")
                or context.get("prompt")
                or ""
            )
            return self._run_sync(self.step(instruction))
        elif action == "close":
            return self._run_sync(self.close())
        
        return {"error": f"Unknown action: {action_id}"}

    async def run_goal(self, goal: str, headless: bool = False, muted: bool = False, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.info(f"Skill executing run_goal with intent: '{goal}'")
        await self._ensure_runtime(headless=headless, muted=muted)
        
        # Playback integration
        playback_service = (context or {}).get("playback_service")
        session_id = (context or {}).get("session_id", "default")
        run_id = f"browser_{int(asyncio.get_running_loop().time() * 1000)}"
        
        if playback_service:
            playback_service.start_run(
                session_id=session_id,
                run_id=run_id,
                title=f"Browser: {goal[:50]}...",
                source={"skill": "browser_control", "action": "run_goal"}
            )
            
            # Notify frontend about the playback run so the card appears in the chat
            callbacks = (context or {}).get("callbacks")
            if callbacks and 'send_status' in callbacks:
                callbacks['send_status']('executing', {
                    'action': 'browser.control.run',
                    'label': f"Navegando: {goal[:50]}...",
                    'playback': {
                        'run_id': run_id,
                        'session_id': session_id,
                        'status': 'running'
                    }
                })

        try:
            # subagent.run_to_goal returns a ToonResponse Pydantic model
            response = await self._subagent.run_to_goal(goal, playback_service=playback_service, run_id=run_id, session_id=session_id)

            # Prepare structured result with playback metadata if available
            result_data = {"ok": True}
            if hasattr(response, "model_dump"):
                result_data["result"] = response.model_dump(mode='json')
            else:
                result_data["result"] = str(response)
            
            if playback_service:
                result_data["playback"] = {
                    "run_id": run_id,
                    "session_id": session_id,
                    "status": "completed"
                }
            return result_data
        except Exception as e:
            logger.error(f"Error in run_goal: {e}")
            return {"ok": False, "error": str(e)}
        finally:
            if playback_service:
                playback_service.end_run(session_id, run_id, status="completed")
                
                # Notify frontend about playback completion
                callbacks = (context or {}).get("callbacks")
                if callbacks and 'send_status' in callbacks:
                    callbacks['send_status']('executing', {
                        'action': 'browser.control.run',
                        'label': "Gravado.",
                        'playback': {
                            'run_id': run_id,
                            'session_id': session_id,
                            'status': 'completed'
                        }
                    })

    async def step(self, instruction: str) -> Dict[str, Any]:
        await self._ensure_runtime()
        # For simplicity, we can use the subagent's logic or a direct runtime call
        # Let's just mock a single step for now or use the subagent if it supports it
        return {"ok": False, "error": "Step-by-step mode not fully implemented in skill wrapper yet."}

    async def close(self) -> Dict[str, Any]:
        if self._runtime:
            await self._runtime.close()
            self._runtime = None
            self._subagent = None
        return {"ok": True}
