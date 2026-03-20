from __future__ import annotations

import os
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from utils.logging_config import get_logger

logger = get_logger("MCPRuntimeService")


@dataclass
class MCPServiceConfig:
    enabled: bool
    endpoint: str
    command: str
    startup_timeout_s: float
    autorestart: bool
    require_healthy: bool


class MCPRuntimeServiceManager:
    def __init__(self, *, logs_dir: str):
        self.logs_dir = str(logs_dir or "")
        self._cfg = MCPServiceConfig(
            enabled=False,
            endpoint="",
            command="",
            startup_timeout_s=20.0,
            autorestart=True,
            require_healthy=True,
        )
        self._proc: Optional[subprocess.Popen] = None
        self._log_handle = None
        self._managed_by_kernel = False

    @staticmethod
    def _to_bool(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _parse_endpoint_host_port(endpoint: str) -> Tuple[str, int]:
        parsed = urlparse(str(endpoint or "").strip())
        host = str(parsed.hostname or "").strip()
        port = int(parsed.port or 0)
        return host, port

    @classmethod
    def _is_local_host(cls, host: str) -> bool:
        h = str(host or "").strip().lower()
        return h in {"127.0.0.1", "localhost", "::1"}

    @classmethod
    def _is_endpoint_reachable(cls, endpoint: str, timeout_s: float = 0.4) -> bool:
        host, port = cls._parse_endpoint_host_port(endpoint)
        if not host or port <= 0:
            return False
        try:
            with socket.create_connection((host, port), timeout=max(0.1, float(timeout_s))):
                return True
        except Exception:
            return False

    def configure_from_browser_cfg(self, browser_cfg: Dict[str, Any]) -> None:
        cfg = browser_cfg if isinstance(browser_cfg, dict) else {}
        mode = str(cfg.get("playwright_transport_mode", "local") or "local").strip().lower()
        endpoint = str(cfg.get("playwright_mcp_endpoint", "") or "").strip()
        autostart_enabled = self._to_bool(cfg.get("playwright_mcp_autostart_enabled", True), True)
        command = str(
            cfg.get("playwright_mcp_server_command")
            or os.environ.get("AOSD_PLAYWRIGHT_MCP_SERVER_COMMAND", "")
        ).strip()
        startup_timeout_s = float(cfg.get("playwright_mcp_startup_timeout_s", 20.0) or 20.0)
        autorestart = self._to_bool(cfg.get("playwright_mcp_autorestart", True), True)
        require_healthy = self._to_bool(cfg.get("playwright_mcp_autostart_require_healthy", True), True)

        self._cfg = MCPServiceConfig(
            enabled=bool(autostart_enabled and mode == "mcp" and endpoint),
            endpoint=endpoint,
            command=command,
            startup_timeout_s=max(3.0, startup_timeout_s),
            autorestart=bool(autorestart),
            require_healthy=bool(require_healthy),
        )

    def is_required(self) -> bool:
        return bool(self._cfg.enabled and self._cfg.require_healthy)

    def start(self) -> Dict[str, Any]:
        if not self._cfg.enabled:
            return {"ok": True, "managed": False, "reason": "autostart_disabled_or_not_mcp"}

        if self._is_endpoint_reachable(self._cfg.endpoint):
            return {"ok": True, "managed": False, "reason": "endpoint_already_reachable"}

        host, _port = self._parse_endpoint_host_port(self._cfg.endpoint)
        if not self._is_local_host(host):
            return {
                "ok": False,
                "managed": False,
                "reason": f"endpoint_not_local:{host}",
            }

        if not self._cfg.command:
            return {"ok": False, "managed": False, "reason": "missing_server_command"}

        try:
            os.makedirs(self.logs_dir, exist_ok=True)
            log_path = os.path.join(self.logs_dir, "playwright_mcp_server.log")
            self._log_handle = open(log_path, "a", encoding="utf-8")
            args = shlex.split(self._cfg.command)
            if not args:
                return {"ok": False, "managed": False, "reason": "invalid_server_command"}
            self._proc = subprocess.Popen(
                args,
                stdout=self._log_handle,
                stderr=self._log_handle,
                cwd=os.getcwd(),
                env=dict(os.environ),
                start_new_session=True,
            )
            self._managed_by_kernel = True
        except Exception as e:
            return {"ok": False, "managed": False, "reason": f"spawn_failed:{e}"}

        deadline = time.time() + float(self._cfg.startup_timeout_s)
        while time.time() < deadline:
            if self._proc and self._proc.poll() is not None:
                rc = self._proc.returncode
                self._proc = None
                return {"ok": False, "managed": True, "reason": f"process_exited:{rc}"}
            if self._is_endpoint_reachable(self._cfg.endpoint):
                pid = int(self._proc.pid) if self._proc else 0
                return {"ok": True, "managed": True, "reason": "started", "pid": pid}
            time.sleep(0.25)

        self.stop()
        return {"ok": False, "managed": True, "reason": "startup_timeout"}

    def ensure_running(self) -> Dict[str, Any]:
        if not self._cfg.enabled:
            return {"ok": True, "reason": "disabled"}
        if self._is_endpoint_reachable(self._cfg.endpoint):
            return {"ok": True, "reason": "healthy"}
        if not self._cfg.autorestart:
            return {"ok": False, "reason": "unreachable_no_autorestart"}
        return self.start()

    def stop(self) -> Dict[str, Any]:
        proc = self._proc
        self._proc = None
        self._managed_by_kernel = False
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=8)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
        return {"ok": True}

