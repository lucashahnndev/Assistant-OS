import logging
import os
import json
import re
from typing import Any, Dict, List
from PIL import Image

from ..base import SkillBase
from ..shared.ephemeral_artifacts import build_temp_media_filename, prune_temp_artifacts_from_path

logger = logging.getLogger("VisionSkill")


class VisionSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "vision"
        self._temp_artifacts_ttl_ms = int(self.config.get("temp_artifacts_ttl_ms") or 300000)

    @property
    def name(self) -> str:
        return "vision"

    @property
    def actions(self) -> List[str]:
        return ["analyze", "search_screen", "locate_screen"]

    @staticmethod
    def _result(ok: bool, status: str, message: str, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": ok, "status": status, "error_details": message}
        payload.update(extra)
        return payload

    @staticmethod
    def _normalize_llm_output(result: Any, default_message: str) -> Dict[str, Any]:
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
            # Remove forbidden fields if they came from LLM
            for f in ["text", "message", "reply"]:
                normalized.pop(f, None)
            
            normalized.setdefault("ok", not has_error_text)
            normalized.setdefault("status", "error" if has_error_text else "success")
            normalized["analysis"] = normalized.get("response") or text_value
            return normalized
        
        text = str(result) if result is not None else default_message
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
            "analysis": text,
            "raw_result": result,
            **({"error_code": "VISION_ANALYSIS_FAILED", "error_details": text} if has_error_text else {}),
        }

    @staticmethod
    def _extract_json_object(raw: Any) -> Dict[str, Any] | None:
        if isinstance(raw, dict):
            return dict(raw)
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        if text.startswith("```"):
            fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
            if fence:
                candidate = fence.group(1).strip()
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
        decoder = json.JSONDecoder()
        for i, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[i:])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
        return None

    @staticmethod
    def _normalize_bbox(payload: Dict[str, Any], fallback_label: str) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {
            "label": str(payload.get("label") or fallback_label or "target"),
            "confidence": float(payload.get("confidence") or 0.0),
            "x": float(payload.get("x") or 0),
            "y": float(payload.get("y") or 0),
            "width": float(payload.get("width") or 0),
            "height": float(payload.get("height") or 0),
        }
        if payload.get("screen_id") is not None:
            try:
                normalized["screen_id"] = int(payload.get("screen_id"))
            except Exception:
                pass
        return normalized

    @staticmethod
    def _normalize_bbox_anchor(payload: Dict[str, Any], bbox: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enforces top-left bbox convention.
        Some vision outputs may provide center-based x/y (or cx/cy fields).
        """
        fixed = dict(bbox or {})
        w = float(fixed.get("width") or 0.0)
        h = float(fixed.get("height") or 0.0)
        if w <= 0 or h <= 0:
            return fixed

        origin = str(payload.get("origin") or payload.get("anchor") or "").strip().lower()
        if origin in {"center", "centre", "mid", "middle"}:
            fixed["x"] = float(round(float(fixed.get("x") or 0.0) - (w / 2.0), 2))
            fixed["y"] = float(round(float(fixed.get("y") or 0.0) - (h / 2.0), 2))
            return fixed

        cx_raw = payload.get("cx")
        if cx_raw is None:
            cx_raw = payload.get("center_x")
        cy_raw = payload.get("cy")
        if cy_raw is None:
            cy_raw = payload.get("center_y")
        if cx_raw is not None and cy_raw is not None:
            try:
                cx = float(cx_raw)
                cy = float(cy_raw)
                fixed["x"] = float(round(cx - (w / 2.0), 2))
                fixed["y"] = float(round(cy - (h / 2.0), 2))
            except Exception:
                pass
        return fixed

    @staticmethod
    def _scale_bbox_from_1000(bbox: Dict[str, Any], img_w: int, img_h: int) -> Dict[str, Any]:
        scaled = dict(bbox)
        scaled["x"] = float(round((float(bbox.get("x") or 0.0) / 1000.0) * float(img_w), 2))
        scaled["y"] = float(round((float(bbox.get("y") or 0.0) / 1000.0) * float(img_h), 2))
        scaled["width"] = float(round((float(bbox.get("width") or 0.0) / 1000.0) * float(img_w), 2))
        scaled["height"] = float(round((float(bbox.get("height") or 0.0) / 1000.0) * float(img_h), 2))
        return scaled

    @staticmethod
    def _scale_bbox_to_1000(bbox: Dict[str, Any], img_w: int, img_h: int) -> Dict[str, Any]:
        if img_w <= 0 or img_h <= 0:
            return dict(bbox)
        scaled = dict(bbox)
        scaled["x"] = float(round((float(bbox.get("x") or 0.0) / float(img_w)) * 1000.0, 2))
        scaled["y"] = float(round((float(bbox.get("y") or 0.0) / float(img_h)) * 1000.0, 2))
        scaled["width"] = float(round((float(bbox.get("width") or 0.0) / float(img_w)) * 1000.0, 2))
        scaled["height"] = float(round((float(bbox.get("height") or 0.0) / float(img_h)) * 1000.0, 2))
        scaled["coordinate_space"] = "normalized_1000"
        return scaled

    @staticmethod
    def _bbox_fits_1000_grid(bbox: Dict[str, Any]) -> bool:
        x = float(bbox.get("x") or 0.0)
        y = float(bbox.get("y") or 0.0)
        w = float(bbox.get("width") or 0.0)
        h = float(bbox.get("height") or 0.0)
        if w <= 0 or h <= 0:
            return False
        if x < 0 or y < 0:
            return False
        return (x + w) <= 1000.0 and (y + h) <= 1000.0

    @staticmethod
    def _read_image_size(path: str) -> tuple[int, int] | None:
        try:
            with Image.open(path) as img:
                w, h = img.size
            if w > 0 and h > 0:
                return int(w), int(h)
        except Exception:
            return None
        return None

    @staticmethod
    def _bbox_inside_image(bbox: Dict[str, Any], img_w: int, img_h: int) -> bool:
        x = float(bbox.get("x") or 0)
        y = float(bbox.get("y") or 0)
        w = float(bbox.get("width") or 0)
        h = float(bbox.get("height") or 0)
        if w <= 0 or h <= 0:
            return False
        if x < 0 or y < 0:
            return False
        if x + w > img_w or y + h > img_h:
            return False
        return True

    @staticmethod
    def _bbox_intersection_ratio(bbox: Dict[str, Any], img_w: int, img_h: int) -> float:
        x = float(bbox.get("x") or 0)
        y = float(bbox.get("y") or 0)
        w = float(bbox.get("width") or 0)
        h = float(bbox.get("height") or 0)
        if w <= 0 or h <= 0:
            return 0.0
        x1, y1 = x, y
        x2, y2 = x + w, y + h
        ix1 = max(0.0, x1)
        iy1 = max(0.0, y1)
        ix2 = min(float(img_w), x2)
        iy2 = min(float(img_h), y2)
        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        inter = iw * ih
        area = max(1.0, w * h)
        return float(inter / area)

    @staticmethod
    def _clamp_bbox_to_image(bbox: Dict[str, Any], img_w: int, img_h: int) -> Dict[str, Any]:
        x = float(bbox.get("x") or 0)
        y = float(bbox.get("y") or 0)
        w = max(1.0, float(bbox.get("width") or 1))
        h = max(1.0, float(bbox.get("height") or 1))

        x = max(0.0, min(x, float(img_w - 1)))
        y = max(0.0, min(y, float(img_h - 1)))

        max_w = max(1.0, float(img_w) - x)
        max_h = max(1.0, float(img_h) - y)
        w = max(1.0, min(w, max_w))
        h = max(1.0, min(h, max_h))

        fixed = dict(bbox)
        fixed["x"] = float(round(x, 2))
        fixed["y"] = float(round(y, 2))
        fixed["width"] = float(round(w, 2))
        fixed["height"] = float(round(h, 2))
        return fixed

    @classmethod
    def _try_dpi_rescale_bbox(cls, bbox: Dict[str, Any], img_w: int, img_h: int) -> Dict[str, Any] | None:
        x = float(bbox.get("x") or 0)
        y = float(bbox.get("y") or 0)
        w = float(bbox.get("width") or 0)
        h = float(bbox.get("height") or 0)
        if w <= 0 or h <= 0:
            return None
        for scale in (1.25, 1.5, 1.75, 2.0):
            candidate = dict(bbox)
            candidate["x"] = float(round(x / scale, 2))
            candidate["y"] = float(round(y / scale, 2))
            candidate["width"] = float(round(max(1.0, w / scale), 2))
            candidate["height"] = float(round(max(1.0, h / scale), 2))
            if cls._bbox_inside_image(candidate, img_w, img_h):
                return candidate
        return None

    @classmethod
    def _maybe_convert_bbox_coordinate_space(
        cls,
        *,
        parsed_payload: Dict[str, Any],
        bbox: Dict[str, Any],
        img_w: int,
        img_h: int,
        label: str,
        hint: str,
    ) -> tuple[Dict[str, Any], bool, str]:
        raw_space = str(
            parsed_payload.get("coordinate_space")
            or parsed_payload.get("coord_space")
            or parsed_payload.get("space")
            or ""
        ).strip().lower()
        normalized_markers = {"normalized_1000", "grid_1000", "0-1000", "1000"}
        if raw_space in normalized_markers and cls._bbox_fits_1000_grid(bbox):
            return cls._scale_bbox_from_1000(bbox, img_w, img_h), True, raw_space
        return bbox, False, raw_space

    @staticmethod
    def _looks_like_screen_request(params: Dict[str, Any], context: Dict[str, Any]) -> bool:
        text_parts = [
            str(params.get("query") or ""),
            str(params.get("prompt") or ""),
            str(context.get("user_input") or ""),
        ]
        haystack = " ".join(text_parts).strip().lower()
        if not haystack:
            return False
        hints = (
            "tela",
            "ecra",
            "ecrã",
            "screen",
            "desktop",
            "janela",
            "window",
            "monitor",
            "display",
            "o que está na tela",
            "oque está na tela",
            "descreva a tela",
        )
        return any(token in haystack for token in hints)

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
        llm_manager = context.get("llm_manager") if isinstance(context, dict) else None
        if not llm_manager:
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
                message="LLMManager not available on Kernel or Orchestrator.",
                error_code="LLM_MANAGER_UNAVAILABLE",
            )

        if action == "analyze":
            path = self._extract_image_path(params)
            prompt = params.get("prompt", "Descreva esta imagem em detalhes.")

            if not path:
                if self._looks_like_screen_request(params, context):
                    # Defensive fallback: if planner chose analyze without image_path
                    # for a screen request, route to search_screen instead of failing.
                    screen_query = str(params.get("query") or prompt or "").strip() or "Descreva resumidamente a tela atual."
                    return self.execute("vision.search_screen", {"query": screen_query}, context)
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'image_path' (or alias 'file_path', 'filename', 'attachment_path').",
                    error_code="MISSING_IMAGE_PATH",
                )

            path = self._resolve_image_path(path, context)

            if not os.path.isfile(path):
                return self._result(
                    ok=False,
                    status="error",
                    message=f"Image file not found: {path}",
                    error_code="IMAGE_NOT_FOUND",
                    path=path,
                )

            llm_result = llm_manager.analyze_image(path, prompt)
            normalized = self._normalize_llm_output(llm_result, default_message="Image analyzed successfully.")
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
                    message="SystemDriver not available.",
                    error_code="SYSTEM_DRIVER_UNAVAILABLE",
                )

            sid = context.get("session_id")
            screenshot_path = sd.take_screenshot(
                filename=build_temp_media_filename("vision_temp", context),
                session_id=sid,
            )
            prune_temp_artifacts_from_path(screenshot_path, self._temp_artifacts_ttl_ms)

            if isinstance(screenshot_path, str) and screenshot_path.startswith("Error"):
                return self._result(
                    ok=False,
                    status="error",
                    message=f"Screenshot capture failed: {screenshot_path}",
                    error_code="SCREENSHOT_FAILED",
                    message=screenshot_path,
                )

            # 2. Analyze
            llm_result = llm_manager.analyze_image(screenshot_path, query)
            normalized = self._normalize_llm_output(llm_result, default_message="Screen analyzed successfully.")
            normalized["path"] = screenshot_path
            normalized["query"] = query
            return normalized

        elif action == "locate_screen":
            label = str(
                params.get("label")
                or params.get("query")
                or params.get("target")
                or params.get("target_description")
                or params.get("target_desc")
                or params.get("description")
                or params.get("object")
                or params.get("element")
                or ""
            ).strip()
            hint = str(params.get("hint") or params.get("target_description") or "").strip()
            if not label:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'label' (or alias 'query').",
                    error_code="MISSING_LABEL",
                )

            sd = context.get("system_driver") or getattr(self.kernel, "system_driver", None)
            if not sd:
                return self._result(
                    ok=False,
                    status="error",
                    message="SystemDriver not available.",
                    error_code="SYSTEM_DRIVER_UNAVAILABLE",
                )

            sid = context.get("session_id")
            screenshot_path = sd.take_screenshot(
                filename=build_temp_media_filename("vision_locator", context),
                session_id=sid,
            )
            prune_temp_artifacts_from_path(screenshot_path, self._temp_artifacts_ttl_ms)
            if isinstance(screenshot_path, str) and screenshot_path.startswith("Error"):
                return self._result(
                    ok=False,
                    status="error",
                    message=f"Screenshot capture failed: {screenshot_path}",
                    error_code="SCREENSHOT_FAILED",
                    message=screenshot_path,
                )
            image_size = self._read_image_size(screenshot_path)
            size_hint = ""
            if image_size:
                size_hint = f"Image size is {image_size[0]}x{image_size[1]} pixels. "

            prompt = (
                "Locate exactly one UI element in this screenshot and return ONLY valid JSON with this schema: "
                "{\"found\":true|false,\"label\":string,\"confidence\":number,\"x\":number,\"y\":number,"
                "\"width\":number,\"height\":number,\"screen_id\":number,\"coordinate_space\":string}. "
                f"Target description: {label}. "
                + size_hint +
                "Return coordinates in normalized 0..1000 grid (x,y,width,height in [0,1000]) "
                "relative to the full screenshot, and set coordinate_space='normalized_1000'. "
                "IMPORTANT: x and y are the TOP-LEFT corner of the bounding box, never the center. "
                "If not found, return found=false and keep numbers as 0."
            )
            if hint:
                prompt += f" Extra hint: {hint}."

            llm_result = llm_manager.analyze_image(screenshot_path, prompt)
            parsed = self._extract_json_object(llm_result)
            if not isinstance(parsed, dict):
                return self._result(
                    ok=False,
                    status="error",
                    message="Vision model did not return valid JSON bbox.",
                    error_code="LOCATOR_PARSE_FAILED",
                    raw=str(llm_result)[:4000],
                    path=screenshot_path,
                )

            found = bool(parsed.get("found", True))
            bbox = self._normalize_bbox(parsed, fallback_label=label)
            bbox = self._normalize_bbox_anchor(parsed, bbox)
            corrected = False
            detected_coordinate_space = "pixels"
            if not found or bbox["width"] <= 0 or bbox["height"] <= 0:
                return self._result(
                    ok=False,
                    status="error",
                    message=f"Element not found: {label}",
                    error_code="ELEMENT_NOT_FOUND",
                    bbox=bbox,
                    path=screenshot_path,
                )
            if image_size:
                bbox, converted_from_1000, detected_coordinate_space = self._maybe_convert_bbox_coordinate_space(
                    parsed_payload=parsed,
                    bbox=bbox,
                    img_w=image_size[0],
                    img_h=image_size[1],
                    label=label,
                    hint=hint,
                )
                if converted_from_1000:
                    corrected = True

            if image_size and not self._bbox_inside_image(bbox, image_size[0], image_size[1]):
                # Retry once with stricter bounded instructions.
                retry_prompt = (
                    "Your previous bbox was out of image bounds. Return corrected JSON only with same schema. "
                    f"Image size is {image_size[0]}x{image_size[1]} pixels. "
                    "Return normalized 0..1000 coordinates and set coordinate_space='normalized_1000'. "
                    "Enforce: 0<=x<=1000, 0<=y<=1000, width>0, height>0, x+width<=1000, y+height<=1000. "
                    f"Target description: {label}. "
                    f"Previous bbox: {json.dumps(bbox, ensure_ascii=False)}"
                )
                retry_raw = llm_manager.analyze_image(screenshot_path, retry_prompt)
                retry_parsed = self._extract_json_object(retry_raw)
                if isinstance(retry_parsed, dict) and bool(retry_parsed.get("found", True)):
                    retry_bbox = self._normalize_bbox(retry_parsed, fallback_label=label)
                    retry_bbox = self._normalize_bbox_anchor(retry_parsed, retry_bbox)
                    retry_bbox, retry_scaled, _retry_space = self._maybe_convert_bbox_coordinate_space(
                        parsed_payload=retry_parsed,
                        bbox=retry_bbox,
                        img_w=image_size[0],
                        img_h=image_size[1],
                        label=label,
                        hint=hint,
                    )
                    if retry_scaled:
                        corrected = True
                    if retry_bbox["width"] > 0 and retry_bbox["height"] > 0:
                        bbox = retry_bbox
                        corrected = True

                if not self._bbox_inside_image(bbox, image_size[0], image_size[1]):
                    overlap = self._bbox_intersection_ratio(bbox, image_size[0], image_size[1])
                    if overlap < 0.25:
                        scaled_bbox = self._try_dpi_rescale_bbox(bbox, image_size[0], image_size[1])
                        if scaled_bbox is not None:
                            bbox = scaled_bbox
                            corrected = True
                            overlap = 1.0
                    if overlap < 0.25:
                        # Last-chance recovery: force an in-frame candidate for the same target.
                        recover_prompt = (
                            "The bbox is still outside the image. "
                            "Try one final time and return ONLY JSON with the same schema. "
                            f"Image size is {image_size[0]}x{image_size[1]}. "
                            "Constraints: return normalized 0..1000 coordinates with coordinate_space='normalized_1000'. "
                            "found=false OR a valid bbox with x,y,width,height fully inside 0..1000 bounds. "
                            f"Target description: {label}. "
                            f"Hint: {hint or 'n/a'}."
                        )
                        recover_raw = llm_manager.analyze_image(screenshot_path, recover_prompt)
                        recover_parsed = self._extract_json_object(recover_raw)
                        if isinstance(recover_parsed, dict) and bool(recover_parsed.get("found", True)):
                            recover_bbox = self._normalize_bbox(recover_parsed, fallback_label=label)
                            recover_bbox = self._normalize_bbox_anchor(recover_parsed, recover_bbox)
                            recover_bbox, recover_scaled, _recover_space = self._maybe_convert_bbox_coordinate_space(
                                parsed_payload=recover_parsed,
                                bbox=recover_bbox,
                                img_w=image_size[0],
                                img_h=image_size[1],
                                label=label,
                                hint=hint,
                            )
                            if recover_scaled:
                                corrected = True
                            recover_conf = float(recover_bbox.get("confidence") or 0.0)
                            if (
                                recover_bbox["width"] > 0
                                and recover_bbox["height"] > 0
                                and self._bbox_inside_image(recover_bbox, image_size[0], image_size[1])
                                and recover_conf >= 0.55
                            ):
                                bbox = recover_bbox
                                corrected = True
                            else:
                                return self._result(
                                    ok=False,
                                    status="error",
                                    message=f"Element located out of frame for '{label}'.",
                                    error_code="ELEMENT_OUT_OF_FRAME",
                                    bbox=bbox,
                                    path=screenshot_path,
                                    image_size={"width": image_size[0], "height": image_size[1]},
                                )
                        else:
                            return self._result(
                                ok=False,
                                status="error",
                                message=f"Element located out of frame for '{label}'.",
                                error_code="ELEMENT_OUT_OF_FRAME",
                                bbox=bbox,
                                path=screenshot_path,
                                image_size={"width": image_size[0], "height": image_size[1]},
                            )
                    bbox = self._clamp_bbox_to_image(bbox, image_size[0], image_size[1])
                    corrected = True

            bbox_px = dict(bbox)
            bbox_out = dict(bbox_px)
            output_coordinate_space = detected_coordinate_space
            if image_size:
                bbox_out = self._scale_bbox_to_1000(bbox_px, image_size[0], image_size[1])
                output_coordinate_space = "normalized_1000"

            return self._result(
                ok=True,
                status="success",
                message=f"Element located: {bbox_out['label']}",
                bbox=bbox_out,
                bbox_px=bbox_px,
                path=screenshot_path,
                query=label,
                corrected=corrected,
                detected_coordinate_space=detected_coordinate_space,
                output_coordinate_space=output_coordinate_space,
                image_size={"width": image_size[0], "height": image_size[1]} if image_size else None,
            )

        return self._result(
            ok=False,
            status="error",
            message=f"Unknown vision action: {action_id}",
            error_code="UNKNOWN_ACTION",
        )
