"""External account providers plugin system."""

from .registry import get_provider_registry

__all__ = ["get_provider_registry"]
