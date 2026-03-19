from __future__ import annotations

from typing import Any, Dict, List

from ..base import CapabilityBase
from ..shared.error_contract import error_envelope
from .retrieve import WebRetrieveCapability
from .search import WebSearchCapability


class WebCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "web"

    @property
    def name(self) -> str:
        return "web"

    @property
    def actions(self) -> List[str]:
        return ["search.discover", "retrieve.read", "retrieve.extract"]

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(base or {})
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = WebCapability._deep_merge(out.get(key) or {}, value)
            else:
                out[key] = value
        return out

    def _legacy_config(self, capability_id: str) -> Dict[str, Any]:
        kernel = self.kernel
        cfg_manager = getattr(kernel, "config_manager", None) if kernel else None
        if not cfg_manager or not hasattr(cfg_manager, "get_capability_config"):
            return {}
        try:
            raw = cfg_manager.get_capability_config(capability_id)
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _effective_root_config(self) -> Dict[str, Any]:
        root = self.config if isinstance(self.config, dict) else {}
        live = self._legacy_config("web")
        return self._deep_merge(root, live)

    def _effective_search_config(self) -> Dict[str, Any]:
        root = self._effective_root_config()
        legacy = self._legacy_config("web_search")
        section = root.get("search") if isinstance(root.get("search"), dict) else {}

        # Backward compatibility: if root still uses legacy web_search shape, accept it.
        legacy_shape_tokens = ("search_router", "defaults", "inherit_provider_capabilities")
        root_legacy_shape = any(token in root for token in legacy_shape_tokens)
        root_legacy_cfg = dict(root) if root_legacy_shape else {}

        return self._deep_merge(self._deep_merge(legacy, root_legacy_cfg), section)

    def _effective_retrieve_config(self) -> Dict[str, Any]:
        root = self._effective_root_config()
        legacy = self._legacy_config("web_retrieve")
        section = root.get("retrieve") if isinstance(root.get("retrieve"), dict) else {}
        return self._deep_merge(legacy, section)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        if action_id == "web.search.discover":
            search = WebSearchCapability(self.kernel, self._effective_search_config())
            return search.execute(action_id, params, context)

        if action_id in {"web.retrieve.read", "web.retrieve.extract"}:
            retrieve = WebRetrieveCapability(self.kernel, self._effective_retrieve_config())
            return retrieve.execute(action_id, params, context)

        return error_envelope(
            provider="web",
            error_code="UNKNOWN_ACTION",
            error_message=f"Unknown web action: {action_id}",
            retryable=False,
            elapsed=0,
            warnings=[],
        )
