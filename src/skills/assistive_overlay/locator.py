from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional


class VisionLocator:
    def __init__(self, kernel: Any):
        self.kernel = kernel

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
        return {
            "label": str(payload.get("label") or fallback_label or "target"),
            "confidence": float(payload.get("confidence") or 0.0),
            "x": float(payload.get("x") or 0),
            "y": float(payload.get("y") or 0),
            "width": float(payload.get("width") or 0),
            "height": float(payload.get("height") or 0),
            "screen_id": int(payload.get("screen_id") or 0),
        }

    def _locate_via_vision_skill(
        self,
        label: str,
        session_id: Optional[str],
        hint: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any] | None:
        skill_registry = None
        if isinstance(context, dict):
            skill_registry = context.get("skill_registry")
        if not skill_registry or not hasattr(skill_registry, "get_skill_for_action"):
            return None
        if not skill_registry.get_skill_for_action("vision.locate_screen"):
            return None

        call_context = dict(context or {})
        call_context.setdefault("session_id", session_id)
        try:
            result = skill_registry.dispatch(
                "vision.locate_screen",
                {"label": label, "hint": hint},
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
        if not bbox:
            return {
                "ok": False,
                "status": "error",
                "error": "VISION_LOCATOR_EMPTY_BBOX",
                "text": "vision.locate_screen succeeded without bbox.",
            }
        return {
            "ok": True,
            "status": "success",
            "text": str(result.get("text") or f"Element located: {label}"),
            "bbox": self._normalize_bbox(bbox, fallback_label=label),
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
        if isinstance(routed, dict) and routed.get("ok"):
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

        screenshot_path = system_driver.take_screenshot(filename="overlay_locator.png", session_id=session_id)
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
            "\"width\":number,\"height\":number,\"screen_id\":number}. "
            f"Target description: {label}. "
            "Coordinates must be absolute pixels in the screenshot reference frame. "
            "If not found, return found=false and keep numbers as 0."
        )
        if hint:
            prompt += f" Extra hint: {hint}."

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
