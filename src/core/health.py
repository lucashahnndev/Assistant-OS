import time
from typing import Dict, Any, Optional
from utils.logging_config import get_logger

logger = get_logger("ProviderHealthMonitor")

class ProviderHealthStatus:
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"

class ProviderHealthMonitor:
    """
    Monitors the health and status of external providers (LLMs).
    Can be used to implement circuit breakers and fallback routing.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ProviderHealthMonitor, cls).__new__(cls)
            cls._instance.providers = {}
        return cls._instance

    def _init_provider(self, provider_id: str):
        if provider_id not in self.providers:
            self.providers[provider_id] = {
                "status": ProviderHealthStatus.HEALTHY,
                "reason": "",
                "failures": 0,
                "last_failure_at": 0,
                "last_success_at": 0,
            }

    def record_success(self, provider_id: str):
        """Marks a successful request to the provider."""
        self._init_provider(provider_id)
        p = self.providers[provider_id]
        p["last_success_at"] = time.time()
        
        # Auto-recover if it was degraded
        if p["status"] != ProviderHealthStatus.HEALTHY:
            logger.info(f"Provider {provider_id} recovered to HEALTHY.")
            p["status"] = ProviderHealthStatus.HEALTHY
            p["reason"] = ""
            p["failures"] = 0

    def record_failure(self, provider_id: str, reason: str, is_fatal: bool = False):
        """Marks a failure for a provider. Fatal failures (auth, quota) mark it offline immediately."""
        self._init_provider(provider_id)
        p = self.providers[provider_id]
        p["failures"] += 1
        p["last_failure_at"] = time.time()
        p["reason"] = reason

        if is_fatal:
            p["status"] = ProviderHealthStatus.OFFLINE
            logger.error(f"Provider {provider_id} marked OFFLINE (fatal): {reason}")
        else:
            if p["failures"] >= 3:
                p["status"] = ProviderHealthStatus.DEGRADED
                logger.warning(f"Provider {provider_id} marked DEGRADED after {p['failures']} failures: {reason}")

    def reset_provider(self, provider_id: str):
        """Manually resets a provider to healthy state."""
        self._init_provider(provider_id)
        self.providers[provider_id].update({
            "status": ProviderHealthStatus.HEALTHY,
            "reason": "manually reset",
            "failures": 0
        })
        logger.info(f"Provider {provider_id} manually reset to HEALTHY.")

    def get_status(self, provider_id: str) -> str:
        """Returns the health status of a provider."""
        return self.providers.get(provider_id, {}).get("status", ProviderHealthStatus.HEALTHY)

    def is_available(self, provider_id: str) -> bool:
        """Returns True if the provider is healthy or degraded (but not offline)."""
        status = self.get_status(provider_id)
        return status != ProviderHealthStatus.OFFLINE

    def get_all_health(self) -> Dict[str, Any]:
        """Returns the full health snapshot of all providers."""
        return self.providers.copy()

# Global Instance
health_monitor = ProviderHealthMonitor()
