from __future__ import annotations

import time
from typing import Any, Dict

from .base import OverlayBackend


class NoopOverlayBackend(OverlayBackend):
    """In-memory backend for tests/headless environments."""

    def __init__(self):
        self._running = False
        self._commands: Dict[str, Dict[str, Any]] = {}

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
        self._commands.clear()

    def is_available(self) -> bool:
        return self._running

    def _gc(self) -> None:
        now_ms = int(time.time() * 1000)
        expired = []
        for cid, cmd in self._commands.items():
            ttl_ms = int(cmd.get("ttl_ms") or 0)
            created_ms = int(cmd.get("created_ms") or 0)
            if ttl_ms > 0 and created_ms > 0 and now_ms >= created_ms + ttl_ms:
                expired.append(cid)
        for cid in expired:
            self._commands.pop(cid, None)

    def draw(self, command: Dict[str, Any]) -> Dict[str, Any]:
        self._gc()
        command_id = str(command.get("id") or "").strip()
        if not command_id:
            return {"ok": False, "error": "MISSING_ID", "text": "Command requires an 'id'."}
        payload = dict(command)
        payload["created_ms"] = int(time.time() * 1000)
        self._commands[command_id] = payload
        return {"ok": True, "status": "success", "id": command_id, "active": len(self._commands)}

    def clear_by_id(self, command_id: str) -> Dict[str, Any]:
        self._gc()
        removed = self._commands.pop(command_id, None)
        return {
            "ok": bool(removed is not None),
            "status": "success" if removed is not None else "empty",
            "id": command_id,
            "active": len(self._commands),
        }

    def clear_all(self) -> Dict[str, Any]:
        count = len(self._commands)
        self._commands.clear()
        return {"ok": True, "status": "success", "cleared": count, "active": 0}
