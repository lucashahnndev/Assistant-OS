import webbrowser
import logging
from urllib.parse import quote_plus
from typing import Dict, Any, List
from ..base import SkillBase

logger = logging.getLogger("BrowserAutomatorSkill")

class BrowserAutomatorSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "browser"

    @property
    def name(self) -> str: return "browser_automator"

    @property
    def actions(self) -> List[str]: return ["open", "navigate", "internal_search", "control", "automate", "play_url"]

    @staticmethod
    def _is_error_result(value: Any) -> bool:
        text = str(value or "").lower()
        markers = ["error:", "fatal tool error", "failed", "not initialized", "not running", "traceback", "exception"]
        return any(marker in text for marker in markers)

    @staticmethod
    def _normalize_target(value: str) -> str:
        target = (value or "").strip()
        if not target:
            return target
        if target.startswith(("http://", "https://")):
            return target
        # If it looks like a plain domain, prefer direct open.
        if " " not in target and "." in target:
            return f"https://{target}"
        # Otherwise interpret as search query (LLM-friendly behavior).
        return f"https://www.google.com/search?q={quote_plus(target)}"

    @staticmethod
    def _wrap_result(ok: bool, action: str, message: str, **extra) -> Dict[str, Any]:
        payload = {
            "ok": ok,
            "status": "success" if ok else "error",
            "action": action,
            "message": message,
            "text": message,
        }
        payload.update(extra)
        return payload

    def _resolve_browser_driver(self, context: Dict[str, Any]):
        browser_driver = context.get("browser_driver")
        logger.info(f"[BrowserAutomator] Context browser_driver present: {bool(browser_driver)}")
        logger.info(f"[BrowserAutomator] self.kernel present: {bool(self.kernel)}")
        if not browser_driver and self.kernel:
            browser_driver = getattr(self.kernel, "browser_driver", None)
            logger.info(f"[BrowserAutomator] Fetched browser_driver from kernel: {bool(browser_driver)}")
        if not browser_driver:
            logger.warning("[BrowserAutomator] browser_driver unavailable.")
        return browser_driver

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        browser_driver = self._resolve_browser_driver(context)

        if action == "open" or action == "navigate":
            raw_target = params.get("url") or params.get("query")
            if not raw_target:
                return self._wrap_result(False, action, "Missing URL or query.", error="MISSING_URL")
            url = self._normalize_target(raw_target)
            if browser_driver:
                driver_result = browser_driver.navigate(url, session_id=context.get("session_id"))
                ok = not self._is_error_result(driver_result)
                return self._wrap_result(
                    ok,
                    action,
                    str(driver_result),
                    url=url,
                    provider="browser_driver",
                    raw_result=str(driver_result),
                )
            webbrowser.open(url)
            return self._wrap_result(True, action, f"Opening {url} in system browser.", url=url, provider="system_browser")

        elif action == "play_url":
            raw_target = params.get("url") or params.get("query")
            if not raw_target:
                return self._wrap_result(False, action, "Missing URL for playback.", error="MISSING_URL")
            url = self._normalize_target(raw_target)
            if browser_driver:
                driver_result = browser_driver.navigate_with_autoplay(url, session_id=context.get("session_id"))
                ok = not self._is_error_result(driver_result)
                return self._wrap_result(
                    ok,
                    action,
                    str(driver_result),
                    url=url,
                    provider="browser_driver",
                    raw_result=str(driver_result),
                )
            webbrowser.open(url)
            return self._wrap_result(
                True,
                action,
                f"Opening '{url}' in system browser (autoplay not guaranteed).",
                url=url,
                provider="system_browser",
            )

        elif action == "internal_search":
            query = params.get("query")
            if not query:
                return self._wrap_result(False, action, "Missing internal search query.", error="MISSING_QUERY")
            if browser_driver:
                sid = context.get("session_id")
                # Forces interaction logic (typing in the current page)
                task = f"Find the search bar on the current page, type '{query}' and press enter."
                driver_result = browser_driver.browser_agent(task, session_id=sid)
                ok = not self._is_error_result(driver_result)
                return self._wrap_result(
                    ok,
                    action,
                    str(driver_result),
                    query=query,
                    task=task,
                    provider="browser_driver",
                    raw_result=str(driver_result),
                )
            return self._wrap_result(False, action, "Browser driver not initialized for internal search.", error="BROWSER_DRIVER_UNAVAILABLE")

        elif action == "control":
            sub_action = params.get("action") # play, pause, next, mute
            if not sub_action:
                return self._wrap_result(False, action, "Missing control 'action' parameter.", error="MISSING_CONTROL_ACTION")
            
            if browser_driver:
                result = browser_driver.control_media(sub_action, session_id=context.get("session_id"))
                if result is True:
                     return self._wrap_result(True, action, f"Browser media control '{sub_action}' executed successfully.", control_action=sub_action)
                return self._wrap_result(
                    False,
                    action,
                    f"Browser media control failed for action '{sub_action}'.",
                    control_action=sub_action,
                    error="CONTROL_FAILED",
                )
            return self._wrap_result(False, action, "Browser driver not initialized for media control.", error="BROWSER_DRIVER_UNAVAILABLE")

        elif action == "automate":
            task = params.get("task") or params.get("query")
            if not task:
                return self._wrap_result(False, action, "Missing task for browser automation.", error="MISSING_TASK")
            if browser_driver:
                sid = context.get("session_id")
                driver_result = browser_driver.browser_agent(task, session_id=sid)
                ok = not self._is_error_result(driver_result)
                return self._wrap_result(
                    ok,
                    action,
                    str(driver_result),
                    task=task,
                    provider="browser_driver",
                    raw_result=str(driver_result),
                )
            return self._wrap_result(False, action, "BrowserDriver not initialized.", error="BROWSER_DRIVER_UNAVAILABLE")

        return self._wrap_result(False, action, f"Unknown browser_automator action: {action_id}", error="UNKNOWN_ACTION")

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        return []
