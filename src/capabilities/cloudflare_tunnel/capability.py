import threading
import time
import logging
from ..base import CapabilityBase
from typing import Dict, Any, List
from pycloudflared.util import get_info
import subprocess
import atexit
import re
from server.core.secret_manager import resolve_secret_ref

logger = logging.getLogger("CloudflareTunnelCapability")

class CloudflareTunnelCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "cloudflare.tunnel"
        self._tunnel = None
        self._auth_process = None
        self._anon_process = None
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

            # Override with capability config if provided
            target_port = self.config.get("target_port")
            if target_port:
                try:
                    port = int(target_port)
                except ValueError:
                    logger.warning(f"Invalid target_port {target_port}, using {port}")

            # Resolve auth_token to check if we are doing authenticated mode
            auth_token = None
            if self.config.get("auth_token"):
                auth_token = resolve_secret_ref(self.config.get("auth_token"))

            if auth_token:
                # Use authenticated tunnel
                exe = get_info().executable
                self._auth_process = subprocess.Popen(
                    [exe, "tunnel", "--no-autoupdate", "run", "--token", auth_token],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                atexit.register(self._auth_process.terminate)
                self._is_running = True
                
                # In authenticated mode, the CLI doesn't output the public URL (it's managed in Zero Trust)
                # So we try to get it from the user's config 'domain' setting for UI display purposes
                domain = self.config.get("domain", "")
                self._public_url = f"https://{domain}" if domain else "Managed via Zero Trust"
                logger.info(f"Cloudflare Authenticated Tunnel started for {self._public_url}")
            else:
                # Start anonymous cloudflared tunnel pointing to the local HTTPS port
                exe = get_info().executable
                self._anon_process = subprocess.Popen(
                    [exe, "tunnel", "--url", f"https://127.0.0.1:{port}", "--no-tls-verify"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True
                )
                atexit.register(self._anon_process.terminate)
                
                # Extract URL from stderr
                extracted_url = None
                for _ in range(50):
                    line = self._anon_process.stderr.readline()
                    if not line:
                        break
                    m = re.search(r'(https?://\S+\.trycloudflare\.com)', line)
                    if m:
                        extracted_url = m.group(1)
                        break
                
                if not extracted_url:
                    self._anon_process.terminate()
                    raise Exception("Failed to extract Cloudflare Tunnel URL")
                
                self._public_url = extracted_url
                self._is_running = True
                logger.info(f"Cloudflare Quick Tunnel started at {self._public_url} pointing to local HTTPS port {port}")
        except Exception as e:
            logger.error(f"Failed to start Cloudflare Tunnel: {e}")
            self._is_running = False
            self._public_url = None

    def _stop_tunnel(self):
        if not self._is_running:
            return
        
        try:
            if self._auth_process:
                self._auth_process.terminate()
                self._auth_process = None
            elif self._anon_process:
                self._anon_process.terminate()
                self._anon_process = None
            
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
