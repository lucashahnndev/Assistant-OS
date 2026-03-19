from __future__ import annotations

from typing import Any, Dict

from ..shared.provider_search_capability import ProviderSearchCapabilityBase
from ..shared.search_providers.openalex_provider import OpenAlexProvider


class OpenAlexSearchCapability(ProviderSearchCapabilityBase):
    CAPABILITY_NAME = "openalex_search"
    ACTION_HANDLER = "query"
    NAMESPACE = "openalex.search"
    PROVIDER_LABEL = "openalex"
    DEFAULT_LIMIT = 6
    DEFAULT_LANGUAGE = "en"

    def _provider_cfg(self) -> Dict[str, Any]:
        provider = self.config.get("provider") if isinstance(self.config.get("provider"), dict) else {}
        return provider

    def _build_provider(self) -> OpenAlexProvider:
        cfg = self._provider_cfg()
        defaults = self.config.get("defaults") if isinstance(self.config.get("defaults"), dict) else {}
        return OpenAlexProvider(
            api_base=str(cfg.get("api_base") or "https://api.openalex.org"),
            timeout_ms=int(cfg.get("timeout_ms") or defaults.get("timeout_ms") or 5000),
            retries=int(cfg.get("retries") or defaults.get("retries") or 1),
            enabled=bool(cfg.get("enabled", True)),
        )
