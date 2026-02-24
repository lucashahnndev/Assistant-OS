import logging
import os
from typing import Any, Dict, List

from ..base import SkillBase

logger = logging.getLogger("VisionSkill")


class VisionSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "vision"

    @property
    def name(self) -> str:
        return "vision"

    @property
    def actions(self) -> List[str]:
        return ["analyze", "search_screen"]

    @staticmethod
    def _result(ok: bool, status: str, text: str, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": ok, "status": status, "text": text}
        payload.update(extra)
        return payload

    @staticmethod
    def _normalize_llm_output(result: Any, default_text: str) -> Dict[str, Any]:
        if isinstance(result, dict):
            normalized = dict(result)
            text_value = str(normalized.get("text") or normalized.get("response") or "")
            lowered = text_value.strip().lower()
            has_error_text = (
                lowered.startswith("erro")
                or lowered.startswith("error")
                or "error code:" in lowered
                or "requires more credits" in lowered
            )
            normalized.setdefault("ok", not has_error_text)
            normalized.setdefault("status", "error" if has_error_text else "success")
            normalized.setdefault("text", normalized.get("response") or default_text)
            return normalized
        text = str(result) if result is not None else default_text
        lowered = text.strip().lower()
        has_error_text = (
            lowered.startswith("erro")
            or lowered.startswith("error")
            or "error code:" in lowered
            or "requires more credits" in lowered
        )
        return {
            "ok": not has_error_text,
            "status": "error" if has_error_text else "success",
            "text": text,
            "result": result,
            **({"error": "VISION_ANALYSIS_FAILED"} if has_error_text else {}),
        }

    @staticmethod
    def _extract_image_path(params: Dict[str, Any]) -> str | None:
        for key in ("image_path", "file_path", "filename", "attachment_path", "path", "file"):
            value = params.get(key)
            if value:
                path_value = value
                break
        else:
            return None

        if isinstance(path_value, list) and path_value:
            path_value = path_value[0]

        if isinstance(path_value, dict):
            for key in ("path", "image_path", "file_path", "filename", "attachment_path", "file"):
                nested_value = path_value.get(key)
                if nested_value:
                    path_value = nested_value
                    break

        if path_value is None:
            return None

        path_text = str(path_value).strip()
        return path_text or None

    def _resolve_image_path(self, raw_path: str, context: Dict[str, Any]) -> str:
        path = (raw_path or "").strip()
        if not path:
            return path

        normalized_input = path.replace("\\", "/")

        # Accept UI proxy paths such as /api/sessions/{id}/files/media/image/file.png
        if "/api/sessions/" in normalized_input and "/files/" in normalized_input:
            normalized_input = normalized_input.split("/files/", 1)[1]

        ws_service = getattr(self.kernel, "workspace_service", None)
        sid = context.get("session_id")

        candidates: List[str] = []

        def add_candidate(candidate: str):
            if candidate:
                candidates.append(os.path.normpath(candidate))

        if os.path.isabs(normalized_input):
            add_candidate(normalized_input)
        else:
            if sid and ws_service:
                session_dir = ws_service.get_session_dir(sid)
                if normalized_input.startswith(("media/", "uploads/", "images/")):
                    add_candidate(os.path.join(session_dir, normalized_input))
                else:
                    add_candidate(os.path.join(session_dir, "media", "image", normalized_input))
                    add_candidate(os.path.join(session_dir, "media", normalized_input))
                    add_candidate(os.path.join(session_dir, "uploads", normalized_input))
                    add_candidate(os.path.join(session_dir, normalized_input))

            if ws_service:
                workspace_dir = ws_service.get_workspace_dir()
                add_candidate(os.path.join(workspace_dir, normalized_input))
                add_candidate(os.path.join(workspace_dir, os.path.basename(normalized_input)))

        if sid and ws_service:
            session_dir = ws_service.get_session_dir(sid)
            base_name = os.path.basename(normalized_input)
            add_candidate(os.path.join(session_dir, "media", "image", base_name))
            add_candidate(os.path.join(session_dir, "media", base_name))
            add_candidate(os.path.join(session_dir, "uploads", base_name))

        deduped: List[str] = []
        seen = set()
        for candidate in candidates:
            key = os.path.abspath(candidate)
            if key not in seen:
                seen.add(key)
                deduped.append(candidate)

        for candidate in deduped:
            if os.path.isfile(candidate):
                return candidate

        return normalized_input

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]

        # Robust LLMManager access
        llm_manager = getattr(self.kernel, "llm_manager", None)
        if not llm_manager:
            # Fallback to orchestrator if kernel one isn't set yet
            orchestrator = getattr(self.kernel, "orchestrator", None)
            if orchestrator:
                llm_manager = getattr(orchestrator, "llm_manager", None)

        if not llm_manager:
            return self._result(
                ok=False,
                status="error",
                text="LLMManager not available on Kernel or Orchestrator.",
                error="LLM_MANAGER_UNAVAILABLE",
            )

        if action == "analyze":
            path = self._extract_image_path(params)
            prompt = params.get("prompt", "Descreva esta imagem em detalhes.")

            if not path:
                return self._result(
                    ok=False,
                    status="error",
                    text="Missing required parameter 'image_path' (or alias 'file_path', 'filename', 'attachment_path').",
                    error="MISSING_IMAGE_PATH",
                )

            path = self._resolve_image_path(path, context)

            if not os.path.isfile(path):
                return self._result(
                    ok=False,
                    status="error",
                    text=f"Image file not found: {path}",
                    error="IMAGE_NOT_FOUND",
                    path=path,
                )

            llm_result = llm_manager.analyze_image(path, prompt)
            normalized = self._normalize_llm_output(llm_result, default_text="Image analyzed successfully.")
            normalized["path"] = path
            normalized["prompt"] = prompt
            return normalized

        elif action == "search_screen":
            query = params.get("query", "O que está acontecendo na tela?")

            # 1. Take screenshot
            sd = context.get("system_driver") or getattr(self.kernel, "system_driver", None)
            if not sd:
                return self._result(
                    ok=False,
                    status="error",
                    text="SystemDriver not available.",
                    error="SYSTEM_DRIVER_UNAVAILABLE",
                )

            sid = context.get("session_id")
            screenshot_path = sd.take_screenshot(filename="vision_temp.png", session_id=sid)

            if isinstance(screenshot_path, str) and screenshot_path.startswith("Error"):
                return self._result(
                    ok=False,
                    status="error",
                    text=f"Screenshot capture failed: {screenshot_path}",
                    error="SCREENSHOT_FAILED",
                    message=screenshot_path,
                )

            # 2. Analyze
            llm_result = llm_manager.analyze_image(screenshot_path, query)
            normalized = self._normalize_llm_output(llm_result, default_text="Screen analyzed successfully.")
            normalized["path"] = screenshot_path
            normalized["query"] = query
            return normalized

        return self._result(
            ok=False,
            status="error",
            text=f"Unknown vision action: {action_id}",
            error="UNKNOWN_ACTION",
        )
