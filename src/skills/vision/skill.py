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
            normalized.setdefault("ok", True)
            normalized.setdefault("status", "success")
            normalized.setdefault("text", normalized.get("response") or default_text)
            return normalized
        return {"ok": True, "status": "success", "text": str(result) if result is not None else default_text, "result": result}

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
            path = params.get("image_path") or params.get("file_path")
            prompt = params.get("prompt", "Descreva esta imagem em detalhes.")

            if not path:
                return self._result(
                    ok=False,
                    status="error",
                    text="Missing required parameter 'image_path' (or alias 'file_path').",
                    error="MISSING_IMAGE_PATH",
                )

            # Resolve relative paths
            if not os.path.isabs(path):
                # Priority: Session context
                sid = context.get("session_id")
                if sid:
                    ws_service = getattr(self.kernel, "workspace_service", None)
                    if ws_service:
                        # 1. Try session media/image folder (Standardized)
                        session_media = os.path.join(ws_service.get_session_dir(sid), "media", "image")
                        session_path = os.path.join(session_media, path)
                        
                        if os.path.exists(session_path):
                            path = session_path
                        else:
                            # Extra check for common subfolders
                            found = False
                            for subfolder in ["media", "images", "media/image", "uploads"]:
                                p = os.path.join(ws_service.get_session_dir(sid), subfolder, path)
                                if os.path.exists(p):
                                    path = p
                                    found = True
                                    break
                            
                            if not found:
                                # 3. Try shared workspace
                                path = os.path.join(ws_service.get_workspace_dir(), path)
                else:
                    # Fallback to shared workspace
                    ws_service = getattr(self.kernel, "workspace_service", None)
                    if ws_service:
                        path = os.path.join(ws_service.get_workspace_dir(), path)

            # Final sanity check
            if not os.path.exists(path):
                # One last attempt: absolute path might be in workspace
                ws_service = getattr(self.kernel, "workspace_service", None)
                if ws_service:
                    alt_path = os.path.join(ws_service.get_workspace_dir(), os.path.basename(path))
                    if os.path.exists(alt_path):
                        path = alt_path

            if not os.path.exists(path):
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
