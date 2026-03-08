from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from PIL import Image

from ..shared.ephemeral_artifacts import build_temp_media_filename, prune_temp_artifacts_from_path


class VisionLocator:
    def __init__(self, kernel: Any, temp_artifacts_ttl_ms: int = 300000):
        self.kernel = kernel
        self.temp_artifacts_ttl_ms = max(1000, int(temp_artifacts_ttl_ms or 300000))

    @staticmethod
    def _enrich_hint(label: str, hint: str, user_input: str = "") -> str:
        return " ".join(
            part.strip()
            for part in (str(hint or ""), str(user_input or ""))
            if str(part or "").strip()
        ).strip()

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        raw = str(text or "").strip()
        if not raw:
            return None

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        matches = re.findall(r"\{[\s\S]*\}", raw)
        for chunk in matches:
            try:
                parsed = json.loads(chunk)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
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
        coordinate_space = str(payload.get("coordinate_space") or payload.get("coord_space") or "").strip().lower()
        if coordinate_space:
            normalized["coordinate_space"] = coordinate_space
        if payload.get("screen_id") is not None:
            try:
                normalized["screen_id"] = int(payload.get("screen_id"))
            except Exception:
                pass
        return normalized

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
    def _bbox_to_pixels(bbox: Dict[str, Any], image_size: tuple[int, int] | None) -> Dict[str, Any]:
        normalized = dict(bbox or {})
        if not image_size:
            return normalized
        space = str(normalized.get("coordinate_space") or "").strip().lower()
        if space not in {"normalized_1000", "grid_1000", "0-1000", "1000"}:
            return normalized
        img_w, img_h = image_size
        if img_w <= 0 or img_h <= 0:
            return normalized
        normalized["x"] = float(round((float(normalized.get("x") or 0.0) / 1000.0) * float(img_w), 2))
        normalized["y"] = float(round((float(normalized.get("y") or 0.0) / 1000.0) * float(img_h), 2))
        normalized["width"] = float(round((float(normalized.get("width") or 0.0) / 1000.0) * float(img_w), 2))
        normalized["height"] = float(round((float(normalized.get("height") or 0.0) / 1000.0) * float(img_h), 2))
        normalized["coordinate_space"] = "global"
        return normalized

    def _locate_via_vision_skill(
        self,
        label: str,
        session_id: Optional[str],
        hint: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any] | None:
        user_input = str((context or {}).get("user_input") or "").strip() if isinstance(context, dict) else ""
        enriched_hint = self._enrich_hint(label=label, hint=hint, user_input=user_input)
        skill_registry = None
        if isinstance(context, dict):
            skill_registry = context.get("skill_registry")
        if not skill_registry or not hasattr(skill_registry, "get_skill_for_action"):
            return None
        if not skill_registry.get_skill_for_action("vision.locate_screen"):
            return None

        call_context = dict(context or {})
        call_context.setdefault("session_id", session_id)
        if self.kernel is not None:
            kernel_llm = getattr(self.kernel, "llm_manager", None)
            if kernel_llm is None:
                orchestrator = getattr(self.kernel, "orchestrator", None)
                kernel_llm = getattr(orchestrator, "llm_manager", None) if orchestrator else None
            if kernel_llm is not None:
                call_context.setdefault("llm_manager", kernel_llm)
            kernel_system = getattr(self.kernel, "system_driver", None)
            if kernel_system is not None:
                call_context.setdefault("system_driver", kernel_system)
        try:
            result = skill_registry.dispatch(
                "vision.locate_screen",
                {"label": label, "hint": enriched_hint},
                call_context,
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": "error",
                "error": "VISION_LOCATOR_DISPATCH_FAILED",
                "text": f"Vision locate dispatch failed: {exc}",
            }

        if not isinstance(result, dict):
            return {
                "ok": False,
                "status": "error",
                "error": "VISION_LOCATOR_PROTOCOL_ERROR",
                "text": "vision.locate_screen returned invalid payload.",
            }
        if not result.get("ok"):
            return {
                "ok": False,
                "status": "error",
                "error": str(result.get("error") or "ELEMENT_NOT_FOUND"),
                "text": str(result.get("text") or "Vision locator failed."),
                "bbox": result.get("bbox"),
                "screenshot_path": result.get("path"),
            }

        bbox = result.get("bbox") if isinstance(result.get("bbox"), dict) else {}
        bbox_px = result.get("bbox_px") if isinstance(result.get("bbox_px"), dict) else {}
        if not bbox:
            return {
                "ok": False,
                "status": "error",
                "error": "VISION_LOCATOR_EMPTY_BBOX",
                "text": "vision.locate_screen succeeded without bbox.",
            }
        image_size_payload = result.get("image_size") if isinstance(result.get("image_size"), dict) else {}
        image_size = None
        if image_size_payload:
            try:
                iw = int(image_size_payload.get("width") or 0)
                ih = int(image_size_payload.get("height") or 0)
                if iw > 0 and ih > 0:
                    image_size = (iw, ih)
            except Exception:
                image_size = None
        normalized_bbox = self._normalize_bbox(bbox_px or bbox, fallback_label=label)
        normalized_bbox = self._bbox_to_pixels(normalized_bbox, image_size=image_size)
        return {
            "ok": True,
            "status": "success",
            "text": str(result.get("text") or f"Element located: {label}"),
            "bbox": normalized_bbox,
            "screenshot_path": result.get("path"),
            "via": "vision.locate_screen",
        }

    def locate(
        self,
        label: str,
        session_id: Optional[str] = None,
        hint: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        routed = self._locate_via_vision_skill(label, session_id, hint, context=context)
        if isinstance(routed, dict):
            return routed

        llm_manager = getattr(self.kernel, "llm_manager", None)
        system_driver = getattr(self.kernel, "system_driver", None)

        if not llm_manager:
            return {
                "ok": False,
                "status": "error",
                "error": "LLM_MANAGER_UNAVAILABLE",
                "text": "Vision locator requires llm_manager.",
            }

        if not system_driver:
            return {
                "ok": False,
                "status": "error",
                "error": "SYSTEM_DRIVER_UNAVAILABLE",
                "text": "Vision locator requires system_driver for screenshots.",
            }

        screenshot_path = system_driver.take_screenshot(
            filename=build_temp_media_filename("overlay_locator", context),
            session_id=session_id,
        )
        prune_temp_artifacts_from_path(screenshot_path, self.temp_artifacts_ttl_ms)
        if not isinstance(screenshot_path, str) or not os.path.isfile(screenshot_path):
            return {
                "ok": False,
                "status": "error",
                "error": "SCREENSHOT_FAILED",
                "text": f"Failed to capture screenshot for locator: {screenshot_path}",
            }

        prompt = (
            "Locate exactly one UI element in this screenshot and return ONLY valid JSON with this schema: "
            "{\"found\":true|false,\"label\":string,\"confidence\":number,\"x\":number,\"y\":number,"
            "\"width\":number,\"height\":number,\"screen_id\":number,\"coordinate_space\":string}. "
            f"Target description: {label}. "
            "Return coordinates in normalized 0..1000 grid and set coordinate_space='normalized_1000'. "
            "IMPORTANT: x and y are the TOP-LEFT corner of the bounding box, never the center. "
            "If not found, return found=false and keep numbers as 0."
        )
        enriched_hint = self._enrich_hint(
            label=label,
            hint=hint,
            user_input=str((context or {}).get("user_input") or "").strip() if isinstance(context, dict) else "",
        )
        if enriched_hint:
            prompt += f" Extra hint: {enriched_hint}."

        vision_raw = llm_manager.analyze_image(screenshot_path, prompt)
        if isinstance(vision_raw, dict):
            parsed = vision_raw
        else:
            parsed = self._extract_json(str(vision_raw or ""))

        if not isinstance(parsed, dict):
            return {
                "ok": False,
                "status": "error",
                "error": "LOCATOR_PARSE_FAILED",
                "text": "Vision result did not contain valid JSON bbox.",
                "raw": str(vision_raw)[:4000],
                "screenshot_path": screenshot_path,
            }

        found = bool(parsed.get("found", True))
        bbox = self._normalize_bbox(parsed, fallback_label=label)
        image_size = self._read_image_size(screenshot_path)
        bbox = self._bbox_to_pixels(bbox, image_size=image_size)
        if not found or bbox["width"] <= 0 or bbox["height"] <= 0:
            return {
                "ok": False,
                "status": "error",
                "error": "ELEMENT_NOT_FOUND",
                "text": f"Element not found: {label}",
                "bbox": bbox,
                "screenshot_path": screenshot_path,
            }

        return {
            "ok": True,
            "status": "success",
            "text": f"Element located: {bbox['label']}",
            "bbox": bbox,
            "screenshot_path": screenshot_path,
            "via": "direct_llm",
        }
