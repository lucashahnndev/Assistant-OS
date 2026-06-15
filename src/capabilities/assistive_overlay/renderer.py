from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, Optional

from .backends import NoopOverlayBackend, QtProcessOverlayBackend


class OverlayRendererService:
    """Resident renderer service to avoid recreating overlay backend every call."""

    _instance: "OverlayRendererService | None" = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, config: Optional[Dict[str, Any]] = None) -> "OverlayRendererService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config or {})
            return cls._instance

    def __init__(self, config: Dict[str, Any]):
        self.config = dict(config or {})
        self.backend_name = str(self.config.get("backend") or "qt").strip().lower()
        self.default_ttl_ms = int(self.config.get("default_ttl_ms") or 2200)
        self.allow_wayland = bool(self.config.get("allow_wayland", False))
        self._backend = self._build_backend()
        self._started = False
        self._state_lock = threading.Lock()

    def _build_backend(self):
        if self.backend_name == "noop":
            return NoopOverlayBackend()
        return QtProcessOverlayBackend(allow_wayland=self.allow_wayland)

    def ensure_started(self) -> Dict[str, Any]:
        with self._state_lock:
            if not self._started:
                self._backend.start()
                self._started = True
        if not self._backend.is_available():
            return {
                "ok": False,
                "success": False,
                "status": "error",
                "error": "OVERLAY_BACKEND_UNAVAILABLE",
                "reason": "OVERLAY_BACKEND_UNAVAILABLE",
                "result_summary": "Overlay backend is not available on this runtime.",
                "structured_result": {"backend": self.backend_name},
                "artifacts": [],
                "attachment_delivery": {"status": "none", "confirmed": False},
                "freshness": {"status": "current", "source": "assistive_overlay"},
                "truncated": False,
                "requires_followup": False,
                "next_step_context": {},
                "diagnostics": {"backend": self.backend_name, "parse_status": "unavailable"},
                "text": "Overlay backend is not available on this runtime.",
                "backend": self.backend_name,
            }
        return {
            "ok": True,
            "success": True,
            "status": "success",
            "reason": None,
            "result_summary": "Overlay backend started.",
            "structured_result": {"backend": self.backend_name},
            "artifacts": [],
            "attachment_delivery": {"status": "none", "confirmed": False},
            "freshness": {"status": "current", "source": "assistive_overlay"},
            "truncated": False,
            "requires_followup": False,
            "next_step_context": {},
            "diagnostics": {"backend": self.backend_name},
            "backend": self.backend_name,
        }

    def stop(self) -> None:
        with self._state_lock:
            self._backend.stop()
            self._started = False

    def _normalize_draw_command(self, payload: Dict[str, Any], command_type: str) -> Dict[str, Any]:
        command = dict(payload or {})
        command["type"] = command_type
        command["id"] = str(command.get("id") or f"overlay-{uuid.uuid4().hex[:10]}")
        command.setdefault("color", "#00E5FF")
        command.setdefault("stroke_width", 3)
        command.setdefault("opacity", 0.95)
        ttl_ms = int(command.get("ttl_ms") or self.default_ttl_ms)
        command["ttl_ms"] = max(100, ttl_ms)
        command.setdefault("coordinate_space", "global")
        command["created_ms"] = int(time.time() * 1000)
        return command

    def draw(self, command_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        status = self.ensure_started()
        if not status.get("ok"):
            return status
        command = self._normalize_draw_command(payload, command_type)
        result = self._backend.draw(command)
        if not isinstance(result, dict):
            return {
                "ok": False,
                "success": False,
                "status": "error",
                "error": "OVERLAY_BACKEND_PROTOCOL_ERROR",
                "reason": "OVERLAY_BACKEND_PROTOCOL_ERROR",
                "result_summary": "Overlay backend returned invalid response.",
                "structured_result": {"command": command, "backend": self.backend_name},
                "artifacts": [],
                "attachment_delivery": {"status": "none", "confirmed": False},
                "freshness": {"status": "current", "source": "assistive_overlay"},
                "truncated": False,
                "requires_followup": False,
                "next_step_context": {},
                "diagnostics": {"backend": self.backend_name, "parse_status": "protocol_error"},
                "text": "Overlay backend returned invalid response.",
                "backend": self.backend_name,
            }
        result.setdefault("backend", self.backend_name)
        result.setdefault("command", command)
        return result

    def clear_by_id(self, command_id: str) -> Dict[str, Any]:
        status = self.ensure_started()
        if not status.get("ok"):
            return status
        result = self._backend.clear_by_id(command_id)
        if isinstance(result, dict):
            result.setdefault("backend", self.backend_name)
            return result
        return {
            "ok": False,
            "success": False,
            "status": "error",
            "error": "OVERLAY_BACKEND_PROTOCOL_ERROR",
            "reason": "OVERLAY_BACKEND_PROTOCOL_ERROR",
            "result_summary": "Overlay backend returned invalid response.",
            "structured_result": {"command_id": command_id, "backend": self.backend_name},
            "artifacts": [],
            "attachment_delivery": {"status": "none", "confirmed": False},
            "freshness": {"status": "current", "source": "assistive_overlay"},
            "truncated": False,
            "requires_followup": False,
            "next_step_context": {},
            "diagnostics": {"backend": self.backend_name, "parse_status": "protocol_error"},
            "text": "Overlay backend returned invalid response.",
            "backend": self.backend_name,
        }

    def clear_all(self) -> Dict[str, Any]:
        status = self.ensure_started()
        if not status.get("ok"):
            return status
        result = self._backend.clear_all()
        if isinstance(result, dict):
            result.setdefault("backend", self.backend_name)
            return result
        return {
            "ok": False,
            "success": False,
            "status": "error",
            "error": "OVERLAY_BACKEND_PROTOCOL_ERROR",
            "reason": "OVERLAY_BACKEND_PROTOCOL_ERROR",
            "result_summary": "Overlay backend returned invalid response.",
            "structured_result": {"backend": self.backend_name},
            "artifacts": [],
            "attachment_delivery": {"status": "none", "confirmed": False},
            "freshness": {"status": "current", "source": "assistive_overlay"},
            "truncated": False,
            "requires_followup": False,
            "next_step_context": {},
            "diagnostics": {"backend": self.backend_name, "parse_status": "protocol_error"},
            "text": "Overlay backend returned invalid response.",
            "backend": self.backend_name,
        }
