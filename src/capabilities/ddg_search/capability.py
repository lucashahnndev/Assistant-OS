from __future__ import annotations

from typing import Any, Dict

from ..shared.provider_search_capability import ProviderSearchCapabilityBase
from ..shared.search_providers.ddg_provider import DdgProvider


class DdgSearchCapability(ProviderSearchCapabilityBase):
    CAPABILITY_NAME = "ddg_search"
    ACTION_HANDLER = "query"
    NAMESPACE = "ddg.search"
    PROVIDER_LABEL = "ddg"
    DEFAULT_LIMIT = 6
    DEFAULT_LANGUAGE = "en"

    def _provider_cfg(self) -> Dict[str, Any]:
        provider = self.config.get("provider") if isinstance(self.config.get("provider"), dict) else {}
        return provider

    def _build_provider(self) -> DdgProvider:
        cfg = self._provider_cfg()
        return DdgProvider(enabled=bool(cfg.get("enabled", False)))
