from __future__ import annotations

from typing import Any, Dict, List

from ..base import CapabilityBase
from ..shared.error_contract import error_envelope
from .retrieve import YouTubeRetrieveCapability
from .search import YouTubeSearchCapability


class YouTubeCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "youtube"

    @property
    def name(self) -> str:
        return "youtube"

    @property
    def actions(self) -> List[str]:
        return ["search.find", "retrieve.get"]

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(base or {})
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = YouTubeCapability._deep_merge(out.get(key) or {}, value)
            else:
                out[key] = value
        return out

    def _cfg(self, capability_id: str) -> Dict[str, Any]:
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
        live = self._cfg("youtube")
        return self._deep_merge(root, live)

    @staticmethod
    def _shared_auth_section(root: Dict[str, Any]) -> Dict[str, Any]:
        shared: Dict[str, Any] = {}
        if isinstance(root.get("authSource"), str) and str(root.get("authSource")).strip():
            shared["authSource"] = str(root.get("authSource"))
        if root.get("apiKey") is not None:
            shared["apiKey"] = root.get("apiKey")
        return shared

    def _effective_search_config(self) -> Dict[str, Any]:
        root = self._effective_root_config()
        legacy = self._cfg("youtube_search")
        section = root.get("search") if isinstance(root.get("search"), dict) else {}
        shared = self._shared_auth_section(root)
        return self._deep_merge(self._deep_merge(legacy, shared), section)

    def _effective_retrieve_config(self) -> Dict[str, Any]:
        root = self._effective_root_config()
        legacy = self._cfg("youtube_retrieve")
        section = root.get("retrieve") if isinstance(root.get("retrieve"), dict) else {}
        shared = self._shared_auth_section(root)
        return self._deep_merge(self._deep_merge(legacy, shared), section)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        if action_id == "youtube.search.find":
            search = YouTubeSearchCapability(self.kernel, self._effective_search_config())
            return search.execute(action_id, params, context)

        if action_id == "youtube.retrieve.get":
            retrieve = YouTubeRetrieveCapability(self.kernel, self._effective_retrieve_config())
            return retrieve.execute(action_id, params, context)

        return error_envelope(
            provider="youtube",
            error_code="UNKNOWN_ACTION",
            error_message=f"Unknown youtube action: {action_id}",
            retryable=False,
            elapsed=0,
            warnings=[],
        )
