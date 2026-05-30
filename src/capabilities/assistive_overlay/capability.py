from __future__ import annotations

import re
from typing import Any, Dict, List

from ..base import CapabilityBase
from .debug_render import render_overlay_debug_image
from .intent import build_draw_payload_from_box, normalize_mark_type
from .locator import VisionLocator
from .renderer import OverlayRendererService


DRAW_ACTIONS = {
    "draw_circle",
    "draw_rect",
    "draw_focus_corners",
    "draw_arrow",
    "draw_line",
    "draw_text",
    "draw_path",
}


class AssistiveOverlayCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "overlay.assist"

        renderer_cfg = self.config.get("overlay") if isinstance(self.config.get("overlay"), dict) else self.config
        self.renderer = OverlayRendererService.get_instance(renderer_cfg or {})
        temp_artifacts_ttl_ms = int(renderer_cfg.get("temp_artifacts_ttl_ms") or self.config.get("temp_artifacts_ttl_ms") or 300000)
        self.locator = VisionLocator(kernel, temp_artifacts_ttl_ms=temp_artifacts_ttl_ms)
        debug_cfg = renderer_cfg.get("debug") if isinstance(renderer_cfg.get("debug"), dict) else {}
        self.debug_enabled = bool(debug_cfg.get("enabled", False))
        self.debug_save_on_draw = bool(debug_cfg.get("save_on_draw", False))

    @property
    def name(self) -> str:
        return "overlay_assist"

    @property
    def actions(self) -> List[str]:
        return [
            "highlight_target",
            "draw_circle",
            "draw_rect",
            "draw_focus_corners",
            "draw_arrow",
            "draw_line",
            "draw_text",
            "draw_path",
            "clear_by_id",
            "clear_all",
        ]

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        # Legacy natural-language shortcuts were removed in Phase 4.
        # Visual tool selection must come from the agent/LLM, not from reflex rules.
        return []

    @staticmethod
    def _ok(text: str, **extra: Any) -> Dict[str, Any]:
        payload = {"ok": True, "status": "success"}
        payload.update(extra)
        return payload

    @staticmethod
    def _err(code: str, text: str, **extra: Any) -> Dict[str, Any]:
        payload = {"ok": False, "status": "error", "error": code}
        payload.update(extra)
        return payload

    @staticmethod
    def _local_action(action_id: str) -> str:
        raw = str(action_id or "").strip().lower()
        if raw.startswith("overlay.assist."):
            return raw[len("overlay.assist.") :]
        if raw.startswith("overlay."):
            return raw[len("overlay.") :]
        return raw.split(".")[-1]

    @staticmethod
    def _infer_label_from_text(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        cleaned = re.sub(r"\s+", " ", raw).strip(" ?!.,:;")
        lowered = cleaned.lower()

        patterns = [
            r"(?:onde fica|onde está|mostra|mostrar|aponte|aponta|destaca|destaque|circule|circula)\s+(?:o|a|os|as|um|uma)?\s*(.+)$",
            r"(?:bot[aã]o|icone|ícone)\s+de\s+(.+)$",
        ]
        for pat in patterns:
            m = re.search(pat, lowered, flags=re.IGNORECASE)
            if m and m.group(1):
                candidate = m.group(1).strip(" ?!.,:;")
                if candidate:
                    return candidate

        # Fallback: use a short trimmed phrase.
        return lowered[:120].strip()

    def _infer_target_label(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        explicit = str(
            params.get("label")
            or params.get("target")
            or params.get("query")
            or params.get("target_description")
            or params.get("target_desc")
            or params.get("description")
            or params.get("object")
            or params.get("element")
            or ""
        ).strip()
        if explicit:
            return explicit
        return self._infer_label_from_text(str(context.get("user_input") or ""))

    @staticmethod
    def _validate_draw_params(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action in {"draw_circle", "draw_rect", "draw_focus_corners", "draw_text"}:
            if "x" not in params or "y" not in params:
                return {"ok": False, "error": "MISSING_COORDS", "error_details": "Parameters 'x' and 'y' are required."}
        if action in {"draw_rect", "draw_focus_corners"}:
            if "width" not in params or "height" not in params:
                return {
                    "ok": False,
                    "error": "MISSING_SIZE",
                    "error_details": "Parameters 'width' and 'height' are required.",
                }
        if action in {"draw_line", "draw_arrow"}:
            required = {"x", "y", "x2", "y2"}
            missing = [k for k in required if k not in params]
            if missing:
                return {
                    "ok": False,
                    "error": "MISSING_LINE_COORDS",
                    "error_details": f"Missing required parameters for {action}: {', '.join(sorted(missing))}.",
                }
        if action == "draw_text" and not str(params.get("text") or "").strip():
            return {"ok": False, "error": "MISSING_TEXT", "error_details": "Parameter 'text' is required for draw_text."}
        if action == "draw_path":
            points = params.get("points")
            if not isinstance(points, list) or len(points) < 2:
                return {
                    "ok": False,
                    "error": "INVALID_PATH",
                    "error_details": "Parameter 'points' must be a list with at least 2 points.",
                }
        return {"ok": True}

    def _draw(self, action: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        validation = self._validate_draw_params(action, params)
        if not validation.get("ok"):
            # Recovery path: if missing geometry for draw actions, try locator+highlight flow.
            if str(validation.get("error") or "") in {"MISSING_COORDS", "MISSING_SIZE", "MISSING_LINE_COORDS"}:
                inferred_label = self._infer_target_label(params, context)
                if inferred_label:
                    recovery_params = dict(params)
                    recovery_params.setdefault("label", inferred_label)
                    recovery_params.setdefault("mark_type", action.replace("draw_", ""))
                    return self._highlight_target(recovery_params, context)
            return self._err(validation.get("error") or "INVALID_PARAMS", validation.get("text") or "Invalid params")

        result = self.renderer.draw(action, params)
        if not isinstance(result, dict):
            return self._err("OVERLAY_BACKEND_PROTOCOL_ERROR", "Overlay backend returned invalid data.")
        if not result.get("ok"):
            return self._err(
                str(result.get("error") or "OVERLAY_DRAW_FAILED"),
                str(result.get("text") or "Overlay draw failed."),
                backend=result.get("backend"),
            )
        command = result.get("command") if isinstance(result.get("command"), dict) else {}
        payload = self._ok(
            f"Overlay command {action} sent.",
            id=result.get("id") or command.get("id"),
            backend=result.get("backend"),
            command=command,
        )
        debug_requested = bool(params.get("debug")) or self.debug_save_on_draw or self.debug_enabled
        reference_image_path = str(
            params.get("debug_reference_path")
            or params.get("reference_image_path")
            or ""
        ).strip()
        if debug_requested and reference_image_path and isinstance(command, dict):
            debug_out = render_overlay_debug_image(
                reference_image_path=reference_image_path,
                command=command,
            )
            if debug_out.get("ok"):
                payload["debug_image_path"] = debug_out.get("path")
            else:
                payload["debug_error"] = debug_out
        return payload

    def _highlight_target(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        label = self._infer_target_label(params, context)
        if not label:
            return self._err("MISSING_TARGET", "Parameter 'label' (or target/query) is required.")

        session_id = str(context.get("session_id") or "").strip() or None
        hint = str(params.get("hint") or params.get("target_description") or "").strip()
        if not hint:
            hint = str(context.get("user_input") or "").strip()
        locator_result = self.locator.locate(label=label, session_id=session_id, hint=hint, context=context)
        if not locator_result.get("ok"):
            return self._err(
                str(locator_result.get("error") or "LOCATOR_FAILED"),
                str(locator_result.get("text") or "Failed to locate target element."),
                locator=locator_result,
            )

        located = locator_result.get("bbox") if isinstance(locator_result.get("bbox"), dict) else {}
        mark_type = normalize_mark_type(params.get("mark_type") or params.get("shape") or "focus_corners")
        default_ttl_ms = int((self.config.get("overlay") or {}).get("default_ttl_ms") or self.config.get("default_ttl_ms") or 2200)
        payload = build_draw_payload_from_box(
            mark_type=mark_type,
            located=located,
            params=params,
            default_ttl_ms=default_ttl_ms,
        )
        draw_result = self.renderer.draw(mark_type, payload)
        if not draw_result.get("ok"):
            return self._err(
                str(draw_result.get("error") or "OVERLAY_DRAW_FAILED"),
                str(draw_result.get("text") or "Overlay backend unavailable."),
                locator=locator_result,
            )

        payload = self._ok(
            f"Target '{label}' highlighted using {mark_type}.",
            target=located,
            draw=draw_result.get("command") if isinstance(draw_result.get("command"), dict) else payload,
            screenshot_path=locator_result.get("screenshot_path"),
            backend=draw_result.get("backend"),
        )
        debug_requested = bool(params.get("debug")) or self.debug_enabled
        reference_image_path = str(locator_result.get("screenshot_path") or "").strip()
        draw_command = draw_result.get("command") if isinstance(draw_result.get("command"), dict) else {}
        if debug_requested and reference_image_path and draw_command:
            debug_out = render_overlay_debug_image(
                reference_image_path=reference_image_path,
                command=draw_command,
            )
            if debug_out.get("ok"):
                payload["debug_image_path"] = debug_out.get("path")
            else:
                payload["debug_error"] = debug_out
        return payload

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = self._local_action(action_id)
        payload = params if isinstance(params, dict) else {}

        if action in DRAW_ACTIONS:
            return self._draw(action, payload, context)

        if action == "clear_by_id":
            command_id = str(payload.get("id") or payload.get("command_id") or "").strip()
            if not command_id:
                return self._err("MISSING_ID", "Parameter 'id' (or command_id) is required.")
            result = self.renderer.clear_by_id(command_id)
            if not result.get("ok"):
                return self._err(
                    str(result.get("error") or "OVERLAY_CLEAR_FAILED"),
                    str(result.get("text") or "Failed to clear overlay command."),
                )
            return self._ok("Overlay command cleared.", id=command_id, backend=result.get("backend"))

        if action == "clear_all":
            result = self.renderer.clear_all()
            if not result.get("ok"):
                return self._err(
                    str(result.get("error") or "OVERLAY_CLEAR_FAILED"),
                    str(result.get("text") or "Failed to clear overlay commands."),
                )
            return self._ok("All overlay commands cleared.", backend=result.get("backend"), cleared=result.get("cleared"))

        if action == "highlight_target":
            return self._highlight_target(payload, context)

        return self._err("UNKNOWN_ACTION", f"Unknown overlay action: {action_id}")
