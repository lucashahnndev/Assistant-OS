from __future__ import annotations

from typing import Any, Dict

from ..shared.provider_search_capability import ProviderSearchCapabilityBase
from ..shared.search_providers.brave_provider import BraveProvider


class BraveSearchCapability(ProviderSearchCapabilityBase):
    CAPABILITY_NAME = "brave_search"
    ACTION_HANDLER = "query"
    NAMESPACE = "brave.search"
    PROVIDER_LABEL = "brave"
    DEFAULT_LIMIT = 6
    DEFAULT_LANGUAGE = "en"

    def _provider_cfg(self) -> Dict[str, Any]:
        provider = self.config.get("provider") if isinstance(self.config.get("provider"), dict) else {}
        return provider

    def _build_provider(self) -> BraveProvider:
        cfg = self._provider_cfg()
        defaults = self.config.get("defaults") if isinstance(self.config.get("defaults"), dict) else {}
        return BraveProvider(
            api_base=str(cfg.get("api_base") or "https://api.search.brave.com/res/v1/web/search"),
            api_key=cfg.get("api_key"),
            timeout_ms=int(cfg.get("timeout_ms") or defaults.get("timeout_ms") or 5000),
            retries=int(cfg.get("retries") or defaults.get("retries") or 1),
            enabled=bool(cfg.get("enabled", False)),
        )
