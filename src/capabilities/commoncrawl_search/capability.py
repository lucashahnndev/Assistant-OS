from __future__ import annotations

from typing import Any, Dict

from ..shared.provider_search_capability import ProviderSearchCapabilityBase
from ..shared.search_providers.commoncrawl_provider import CommonCrawlCdxProvider


class CommonCrawlSearchCapability(ProviderSearchCapabilityBase):
    CAPABILITY_NAME = "commoncrawl_search"
    ACTION_HANDLER = "query"
    NAMESPACE = "commoncrawl.search"
    PROVIDER_LABEL = "commoncrawl"
    DEFAULT_LIMIT = 6
    DEFAULT_LANGUAGE = "en"

    def _provider_cfg(self) -> Dict[str, Any]:
        provider = self.config.get("provider") if isinstance(self.config.get("provider"), dict) else {}
        return provider

    def _build_provider(self) -> CommonCrawlCdxProvider:
        cfg = self._provider_cfg()
        defaults = self.config.get("defaults") if isinstance(self.config.get("defaults"), dict) else {}
        return CommonCrawlCdxProvider(
            collinfo_url=str(cfg.get("collinfo_url") or "https://index.commoncrawl.org/collinfo.json"),
            timeout_ms=int(cfg.get("timeout_ms") or defaults.get("timeout_ms") or 6000),
            retries=int(cfg.get("retries") or defaults.get("retries") or 1),
            max_indexes=int(cfg.get("max_indexes") or defaults.get("max_indexes") or 2),
            enabled=bool(cfg.get("enabled", True)),
        )
