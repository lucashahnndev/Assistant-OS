import logging
from ..base import CapabilityBase
from typing import Dict, Any, List
from pyngrok import ngrok, conf
from server.core.secret_manager import resolve_secret_ref

logger = logging.getLogger("NgrokTunnelCapability")

class NgrokTunnelCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "ngrok.tunnel"
        self._tunnel = None
        self._public_url = None
        self._is_running = False
        self._last_error = None

    @property
    def name(self) -> str:
        return "ngrok_tunnel"

    @property
    def actions(self) -> List[str]:
        return ["start", "stop", "status"]

    def _start_tunnel(self):
        if self._is_running:
            return
        self._last_error = None
        
        try:
            auth_token = resolve_secret_ref(self.config.get("auth_token"))
            if auth_token:
                ngrok.set_auth_token(auth_token)
            else:
                logger.info("Ngrok auth_token not provided in config. Relying on system ngrok.yml.")

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
            
            # Setup options with a safe name for the pyngrok API
            options = {"bind_tls": True, "name": f"assistant-os-vite-{port}"}
            domain = self.config.get("domain")
            if domain and domain.strip():
                options["domain"] = domain.strip()
            
            region = self.config.get("region")
            if region and region.strip():
                options["region"] = region.strip()
            
            # Create tunnel mapping to HTTPS local Vite server
            self._tunnel = ngrok.connect(f"https://127.0.0.1:{port}", **options)
            self._public_url = self._tunnel.public_url
            self._is_running = True
            
            logger.info(f"Ngrok Tunnel started at {self._public_url} pointing to local port {port}")
        except Exception as e:
            logger.error(f"Failed to start Ngrok Tunnel: {e}")
            self._is_running = False
            self._public_url = None
            self._last_error = str(e)

    def _stop_tunnel(self):
        if not self._is_running:
            return
        
        try:
            if self._public_url:
                ngrok.disconnect(self._public_url)
            self._tunnel = None
            self._public_url = None
            self._is_running = False
            logger.info("Ngrok Tunnel stopped")
        except Exception as e:
            logger.error(f"Failed to stop Ngrok Tunnel: {e}")
            self._last_error = str(e)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]

        if action == "start":
            self._start_tunnel()
            return {
                "ok": self._is_running,
                "status": "running" if self._is_running else "error",
                "public_url": self._public_url,
                "error_details": self._last_error
            }

        if action == "stop":
            self._stop_tunnel()
            return {
                "ok": not self._is_running,
                "status": "stopped" if not self._is_running else "error",
                "error_details": self._last_error
            }

        if action == "status":
            return {
                "ok": True,
                "provider": "ngrok",
                "status": "running" if self._is_running else "stopped",
                "public_url": self._public_url
            }

        return {
            "ok": False,
            "status": "error",
            "error_code": "UNKNOWN_ACTION",
            "error_details": f"Unknown action: {action_id}",
        }
