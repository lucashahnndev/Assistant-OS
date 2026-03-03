from __future__ import annotations

import importlib
import logging
import pkgutil
from functools import lru_cache
from typing import Dict

from .base import ExternalAccountProvider
from . import providers as providers_pkg

logger = logging.getLogger("ExternalAccountsRegistry")


class ExternalAccountProviderRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, ExternalAccountProvider] = {}

    def register(self, provider: ExternalAccountProvider) -> None:
        key = provider.get_metadata().key.strip().lower()
        if not key:
            raise ValueError("Provider key cannot be empty")
        self._providers[key] = provider

    def get(self, key: str) -> ExternalAccountProvider | None:
        return self._providers.get((key or "").strip().lower())

    def all(self) -> Dict[str, ExternalAccountProvider]:
        return dict(self._providers)

    @classmethod
    def discover(cls) -> "ExternalAccountProviderRegistry":
        registry = cls()
        for module_info in pkgutil.iter_modules(providers_pkg.__path__):
            module_name = f"{providers_pkg.__name__}.{module_info.name}"
            try:
                module = importlib.import_module(module_name)
                if not hasattr(module, "get_provider"):
                    continue
                provider = module.get_provider()
                registry.register(provider)
            except Exception as exc:
                logger.warning("Failed to load external provider plugin '%s': %s", module_name, exc)
        return registry


@lru_cache(maxsize=1)
def get_provider_registry() -> ExternalAccountProviderRegistry:
    return ExternalAccountProviderRegistry.discover()
