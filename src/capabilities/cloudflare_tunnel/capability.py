import threading
import time
import logging
from ..base import CapabilityBase
from typing import Dict, Any, List
from pycloudflared import trycloudflare

logger = logging.getLogger("CloudflareTunnelCapability")

class CloudflareTunnelCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "cloudflare.tunnel"
        self._tunnel = None
        self._public_url = None
        self._is_running = False

    @property
    def name(self) -> str:
        return "cloudflare_tunnel"

    @property
    def actions(self) -> List[str]:
        return ["start", "stop", "status"]

    def _start_tunnel(self):
        if self._is_running:
            return
        
        self._is_running = True
        try:
            # Assuming frontend runs on port 5173
            port = 5173
            if self.kernel and hasattr(self.kernel, 'config_manager'):
                frontend_config = self.kernel.config_manager.get("frontend", {})
                port = frontend_config.get("port", 5173)

            # Start trycloudflare tunnel pointing to the local port
            # Note: trycloudflare might block, so we run it in a thread if it does, but pycloudflared provides a non-blocking wrapper.
            self._tunnel = trycloudflare(port=port)
            self._public_url = self._tunnel.tunnel
            logger.info(f"Cloudflare Tunnel started at {self._public_url}")
        except Exception as e:
            logger.error(f"Failed to start Cloudflare Tunnel: {e}")
            self._is_running = False
            self._public_url = None

    def _stop_tunnel(self):
        if not self._is_running:
            return
        
        try:
            if self._tunnel:
                self._tunnel.stop()
            self._tunnel = None
            self._public_url = None
            self._is_running = False
            logger.info("Cloudflare Tunnel stopped")
        except Exception as e:
            logger.error(f"Failed to stop Cloudflare Tunnel: {e}")

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]

        if action == "start":
            self._start_tunnel()
            return {
                "ok": self._is_running,
                "status": "running" if self._is_running else "error",
                "public_url": self._public_url
            }

        if action == "stop":
            self._stop_tunnel()
            return {
                "ok": True,
                "status": "stopped"
            }

        if action == "status":
            return {
                "ok": True,
                "provider": "cloudflare",
                "status": "running" if self._is_running else "stopped",
                "public_url": self._public_url
            }

        return {
            "ok": False,
            "status": "error",
            "error_code": "UNKNOWN_ACTION",
            "error_details": f"Unknown action: {action_id}",
        }
