import logging
import re
import ast
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
    def _pick_first_str(params: Dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _is_error_result(value: Any) -> bool:
        text = str(value or "").lower()
        markers = [
            "error:",
            "error navigating",
            "fatal tool error",
            "failed",
            "not initialized",
            "not running",
            "client is not started",
            "traceback",
            "exception",
        ]
        return any(marker in text for marker in markers)

    @staticmethod
    def _coerce_structured_result(value: Any) -> Dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            candidate = value.strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                try:
                    parsed = ast.literal_eval(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    return None
        return None

    @staticmethod
    def _normalize_target(value: str) -> str:
        target = (value or "").strip()
        if not target:
            return target

        normalized_target = re.sub(r"\s+", " ", target).strip()
        lowered = normalized_target.lower()
        # Handle common media intents directly instead of generic Google fallback.
        if "youtube music" in lowered or "yt music" in lowered or "ytoutbe music" in lowered or "youtbe music" in lowered:
            query = re.sub(r"(youtube music|yt music|ytoutbe music|youtbe music)", "", normalized_target, flags=re.IGNORECASE).strip(" -")
            if query:
                return f"https://music.youtube.com/search?q={quote_plus(query)}"
            return "https://music.youtube.com/"
        if "music.youtube.com" in lowered:
            if normalized_target.startswith(("http://", "https://")):
                return normalized_target
            return f"https://{normalized_target}"
        if "deezer" in lowered and "track/" not in lowered and "album/" not in lowered and "playlist/" not in lowered:
            query = re.sub(r"deezer", "", normalized_target, flags=re.IGNORECASE).strip(" -")
            if query:
                return f"https://www.deezer.com/search/{quote_plus(query)}"
            return "https://www.deezer.com/"

        if target.startswith(("http://", "https://")):
            return target
        # If it looks like a plain domain, prefer direct open.
        if " " not in target and "." in target:
            return f"https://{target}"
        # Keep media playback intent on media surfaces (avoid generic Google fallback).
        if any(term in lowered for term in ("reproduz", "reproduzir", "reporduz", "toca", "tocar", "play", "música", "musica", "music")):
            return f"https://music.youtube.com/search?q={quote_plus(normalized_target)}"

        # Otherwise interpret as search query (LLM-friendly behavior).
        return f"https://www.google.com/search?q={quote_plus(target)}"

    @staticmethod
    def _infer_query_from_context(params: Dict[str, Any], context: Dict[str, Any]) -> str:
        query = BrowserAutomatorSkill._pick_first_str(
            params,
            ("query", "search_query", "searchQuery", "q", "term", "text"),
        )
        if query:
            return query

        text = str(context.get("user_input") or "").strip()
        if not text:
            return ""

        cleaned = text.lower()
        # Remove command verbs and platform qualifiers, keep content intent.
        patterns = [
            r"\b(reporduz|reproduz|reproduzir|toca|tocar|abre|abrir|open|play)\b",
            r"\b(a|o|uma|um|no|na|de|do|da|dos|das)\b",
            r"\b(youtube music|ytoutbe music|yt music|youtube|deezer|spotify)\b",
            r"\b(musica|música|music)\b",
            r"\s+",
        ]
        for p in patterns[:-1]:
            cleaned = re.sub(p, " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(patterns[-1], " ", cleaned).strip()
        return cleaned

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

    @staticmethod
    def _navigate_driver(browser_driver: Any, url: str, session_id: str | None, purpose: str, device_id: str):
        try:
            return browser_driver.navigate(
                url,
                session_id=session_id,
                purpose=purpose,
                device_id=device_id,
            )
        except TypeError:
            return browser_driver.navigate(url, session_id=session_id)

    @staticmethod
    def _navigate_autoplay_driver(
        browser_driver: Any,
        url: str,
        session_id: str | None,
        device_id: str,
        force_new_media_tab: bool,
    ):
        try:
            return browser_driver.navigate_with_autoplay(
                url,
                session_id=session_id,
                device_id=device_id,
                force_new_media_tab=force_new_media_tab,
            )
        except TypeError:
            return browser_driver.navigate_with_autoplay(url, session_id=session_id)

    @staticmethod
    def _control_media_driver(browser_driver: Any, action: str, session_id: str | None, device_id: str):
        try:
            return browser_driver.control_media(
                action,
                session_id=session_id,
                device_id=device_id,
            )
        except TypeError:
            return browser_driver.control_media(action, session_id=session_id)

    @staticmethod
    def _browser_agent_driver(browser_driver: Any, task: str, session_id: str | None, device_id: str):
        try:
            return browser_driver.browser_agent(task, session_id=session_id, device_id=device_id)
        except TypeError:
            return browser_driver.browser_agent(task, session_id=session_id)

    @staticmethod
    def _infer_control_action(params: Dict[str, Any], context: Dict[str, Any]) -> str:
        query_hint = BrowserAutomatorSkill._pick_first_str(
            params,
            ("query", "search_query", "searchQuery", "q", "term", "text"),
        )
        text_parts = [
            str(params.get("action") or ""),
            query_hint,
            str(params.get("task") or ""),
            str(context.get("user_input") or ""),
        ]
        text = " ".join(text_parts).strip().lower()
        if not text:
            return "play"

        if any(token in text for token in ("pause", "pausa", "pausar")):
            return "pause"
        if any(token in text for token in ("next", "próxima", "proxima", "avançar", "avancar")):
            return "next"
        if any(token in text for token in ("mute", "mudo", "silenciar")):
            return "mute"
        if any(token in text for token in ("fullscreen", "tela cheia")):
            return "fullscreen"
        if any(token in text for token in ("click", "clique")):
            return "click"
        return "play"

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
        device_id = self._pick_first_str(params, ("device_id", "device", "audio_device")) or "default"
        allow_agent_fallback = bool(params.get("allow_agent_fallback", True))
        force_new_media_tab = bool(params.get("force_new_media_tab", False))

        if action == "open" or action == "navigate":
            raw_target = self._pick_first_str(params, ("url", "link", "uri", "query", "search_query", "searchQuery", "q"))
            if not raw_target:
                raw_target = context.get("user_input")
            if not raw_target:
                return self._wrap_result(False, action, "Missing URL or query.", error="MISSING_URL")
            url = self._normalize_target(raw_target)
            if browser_driver:
                if hasattr(browser_driver, "browser_agent"):
                    task = (
                        f"Open this URL on the current browser session: {url}. "
                        "If a consent/cookie banner appears, handle it. "
                        "Stop after confirming the page is loaded."
                    )
                    driver_result = self._browser_agent_driver(
                        browser_driver,
                        task,
                        context.get("session_id"),
                        device_id,
                    )
                    ok = not self._is_error_result(driver_result)
                    return self._wrap_result(
                        ok,
                        action,
                        str(driver_result),
                        url=url,
                        provider="browser_use_agent",
                        device_id=device_id,
                        raw_result=str(driver_result),
                    )
                # Media surfaces (Deezer/YouTube) often need autoplay/user-gesture handling.
                if any(host in url for host in ("deezer.com/track/", "youtube.com/watch", "music.youtube.com/watch")):
                    driver_result = self._navigate_autoplay_driver(
                        browser_driver,
                        url,
                        context.get("session_id"),
                        device_id,
                        force_new_media_tab,
                    )
                else:
                    purpose = "media" if any(host in url for host in ("youtube.com", "music.youtube.com", "deezer.com", "spotify.com")) else "task"
                    driver_result = self._navigate_driver(
                        browser_driver,
                        url,
                        context.get("session_id"),
                        purpose,
                        device_id,
                    )
                structured_result = self._coerce_structured_result(driver_result)
                is_structured = structured_result is not None
                ok = bool(structured_result.get("ok", True)) if is_structured else (not self._is_error_result(driver_result))
                message = str(structured_result.get("message") or structured_result.get("text") or driver_result) if is_structured else str(driver_result)
                if (
                    is_structured
                    and allow_agent_fallback
                    and str(structured_result.get("status", "")).lower() == "partial"
                    and any(host in url for host in ("youtube.com", "music.youtube.com", "deezer.com", "spotify.com"))
                ):
                    task = (
                        f"The media page is already opened ({url}). "
                        "Use current tab only, handle consent overlays, start playback, and confirm media state."
                    )
                    fallback_result = self._browser_agent_driver(
                        browser_driver,
                        task,
                        context.get("session_id"),
                        device_id,
                    )
                    return self._wrap_result(
                        not self._is_error_result(fallback_result),
                        action,
                        str(fallback_result),
                        url=url,
                        provider="browser_driver_agent_fallback",
                        raw_result=str(fallback_result),
                        device_id=device_id,
                    )
                return self._wrap_result(
                    ok,
                    action,
                    message,
                    url=url,
                    provider="browser_driver",
                    device_id=device_id,
                    raw_result=structured_result if is_structured else str(driver_result),
                    playback_confirmed=structured_result.get("playback_confirmed") if is_structured else None,
                    playback_status=structured_result.get("status") if is_structured else None,
                    verification=structured_result.get("verification") if is_structured else None,
                )
            return self._wrap_result(
                False,
                action,
                "Browser driver unavailable. Could not open URL safely.",
                url=url,
                provider="browser_driver",
                error="BROWSER_DRIVER_UNAVAILABLE",
            )

        elif action == "play_url":
            raw_target = self._pick_first_str(params, ("url", "link", "uri", "query", "search_query", "searchQuery", "q"))
            if not raw_target:
                return self._wrap_result(False, action, "Missing URL for playback.", error="MISSING_URL")
            url = self._normalize_target(raw_target)
            if browser_driver:
                if hasattr(browser_driver, "browser_agent"):
                    task = (
                        f"Open this media URL and start playback in the same tab: {url}. "
                        "Handle consent/cookie overlays if needed. "
                        "Confirm playback using on-page media state (playing or currentTime progressing). "
                        "If not possible, return blocker clearly."
                    )
                    driver_result = self._browser_agent_driver(
                        browser_driver,
                        task,
                        context.get("session_id"),
                        device_id,
                    )
                    ok = not self._is_error_result(driver_result)
                    return self._wrap_result(
                        ok,
                        action,
                        str(driver_result),
                        url=url,
                        provider="browser_use_agent",
                        device_id=device_id,
                        raw_result=str(driver_result),
                    )
                driver_result = self._navigate_autoplay_driver(
                    browser_driver,
                    url,
                    context.get("session_id"),
                    device_id,
                    force_new_media_tab,
                )
                structured_result = self._coerce_structured_result(driver_result)
                is_structured = structured_result is not None
                ok = bool(structured_result.get("ok", True)) if is_structured else (not self._is_error_result(driver_result))
                message = str(structured_result.get("message") or structured_result.get("text") or driver_result) if is_structured else str(driver_result)
                if is_structured and allow_agent_fallback and str(structured_result.get("status", "")).lower() == "partial":
                    task = (
                        f"The media page is already opened ({url}). "
                        "Use current tab only, start playback, and confirm media state."
                    )
                    fallback_result = self._browser_agent_driver(
                        browser_driver,
                        task,
                        context.get("session_id"),
                        device_id,
                    )
                    return self._wrap_result(
                        not self._is_error_result(fallback_result),
                        action,
                        str(fallback_result),
                        url=url,
                        provider="browser_driver_agent_fallback",
                        raw_result=str(fallback_result),
                        device_id=device_id,
                    )
                return self._wrap_result(
                    ok,
                    action,
                    message,
                    url=url,
                    provider="browser_driver",
                    device_id=device_id,
                    raw_result=structured_result if is_structured else str(driver_result),
                    playback_confirmed=structured_result.get("playback_confirmed") if is_structured else None,
                    playback_status=structured_result.get("status") if is_structured else None,
                    verification=structured_result.get("verification") if is_structured else None,
                )
            return self._wrap_result(
                False,
                action,
                "Browser driver unavailable. Could not start playback safely.",
                url=url,
                provider="browser_driver",
                error="BROWSER_DRIVER_UNAVAILABLE",
            )

        elif action == "internal_search":
            query = self._pick_first_str(params, ("query", "search_query", "searchQuery", "q", "term", "text")) or self._infer_query_from_context(params, context)
            if not query:
                return self._wrap_result(False, action, "Missing internal search query.", error="MISSING_QUERY")
            if browser_driver:
                sid = context.get("session_id")
                # Forces interaction logic (typing in the current page)
                task = f"Find the search bar on the current page, type '{query}' and press enter."
                driver_result = self._browser_agent_driver(browser_driver, task, sid, device_id)
                ok = not self._is_error_result(driver_result)
                return self._wrap_result(
                    ok,
                    action,
                    str(driver_result),
                    query=query,
                    task=task,
                    provider="browser_driver",
                    device_id=device_id,
                    raw_result=str(driver_result),
                )
            return self._wrap_result(False, action, "Browser driver not initialized for internal search.", error="BROWSER_DRIVER_UNAVAILABLE")

        elif action == "control":
            sub_action = params.get("action") # play, pause, next, mute
            inferred = False
            if not sub_action:
                sub_action = self._infer_control_action(params, context)
                inferred = True
            
            if browser_driver:
                result = self._control_media_driver(
                    browser_driver,
                    sub_action,
                    context.get("session_id"),
                    device_id,
                )
                structured_result = self._coerce_structured_result(result)
                if structured_result is not None:
                    ok = bool(structured_result.get("ok", False))
                    status = str(structured_result.get("status") or ("success" if ok else "error"))
                    message = str(
                        structured_result.get("message")
                        or structured_result.get("text")
                        or f"Browser media control '{sub_action}' completed with status '{status}'."
                    )
                    wrapped = self._wrap_result(
                        ok,
                        action,
                        message,
                        control_action=sub_action,
                        inferred_action=inferred,
                        provider="browser_driver",
                        device_id=device_id,
                        raw_result=structured_result,
                        playback_confirmed=structured_result.get("playback_confirmed"),
                        blocker=structured_result.get("blocker"),
                        details=structured_result.get("details"),
                        verification=structured_result.get("verification"),
                    )
                    if status == "partial":
                        wrapped["ok"] = True
                        wrapped["status"] = "partial"
                    return wrapped

                if result is True:
                    return self._wrap_result(
                        True,
                        action,
                        f"Browser media control '{sub_action}' executed successfully.",
                        control_action=sub_action,
                        inferred_action=inferred
                    )
                return self._wrap_result(
                    False,
                    action,
                    f"Browser media control failed for action '{sub_action}'.",
                    control_action=sub_action,
                    inferred_action=inferred,
                    error="CONTROL_FAILED",
                )
            return self._wrap_result(False, action, "Browser driver not initialized for media control.", error="BROWSER_DRIVER_UNAVAILABLE")

        elif action == "automate":
            task = self._pick_first_str(params, ("task", "instruction", "instructions", "query", "search_query", "searchQuery", "q"))
            if not task:
                return self._wrap_result(False, action, "Missing task for browser automation.", error="MISSING_TASK")
            if browser_driver:
                sid = context.get("session_id")
                driver_result = self._browser_agent_driver(browser_driver, task, sid, device_id)
                ok = not self._is_error_result(driver_result)
                return self._wrap_result(
                    ok,
                    action,
                    str(driver_result),
                    task=task,
                    provider="browser_driver",
                    device_id=device_id,
                    raw_result=str(driver_result),
                )
            return self._wrap_result(False, action, "BrowserDriver not initialized.", error="BROWSER_DRIVER_UNAVAILABLE")

        return self._wrap_result(False, action, f"Unknown browser_automator action: {action_id}", error="UNKNOWN_ACTION")

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        return []
