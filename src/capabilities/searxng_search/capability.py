from __future__ import annotations

from typing import Any, Dict, List

from ..shared.provider_search_capability import ProviderSearchCapabilityBase
from ..shared.search_providers.searxng_provider import SearxngProvider


class SearxngSearchCapability(ProviderSearchCapabilityBase):
    CAPABILITY_NAME = "searxng_search"
    ACTION_HANDLER = "query"
    NAMESPACE = "searxng.search"
    PROVIDER_LABEL = "searxng"
    DEFAULT_LIMIT = 6
    DEFAULT_LANGUAGE = "en"

    def _provider_cfg(self) -> Dict[str, Any]:
        provider = self.config.get("provider") if isinstance(self.config.get("provider"), dict) else {}
        return provider

    @staticmethod
    def _to_str_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        for item in value:
            val = str(item or "").strip()
            if val:
                out.append(val)
        return out

    def _build_provider(self) -> SearxngProvider:
        cfg = self._provider_cfg()
        defaults = self.config.get("defaults") if isinstance(self.config.get("defaults"), dict) else {}
        endpoints = self._to_str_list(cfg.get("endpoints")) or ["https://searx.be", "https://search.inetol.net"]
        engines = self._to_str_list(cfg.get("engines")) or None
        return SearxngProvider(
            endpoints=endpoints,
            engines=engines,
            timeout_ms=int(cfg.get("timeout_ms") or defaults.get("timeout_ms") or 5000),
            retries=int(cfg.get("retries") or defaults.get("retries") or 1),
            enabled=bool(cfg.get("enabled", True)),
        )
