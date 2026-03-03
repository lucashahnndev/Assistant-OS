from typing import Any, Dict, List
import os

from ..base import SkillBase
from ..shared.chunking import chunk_text, clamp_chunk_overlap, clamp_chunk_size
from ..shared.error_contract import error_envelope
from ..shared.retrieval import (
    clamp_cache_ttl,
    clamp_max_chars,
    clamp_max_bytes,
    clamp_rate_limit,
    clamp_retries,
    clamp_timeout_ms,
    extract_structured,
    fetch_and_read,
)


class WebRetrieveSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "web.retrieve"

    @property
    def name(self) -> str:
        return "web_retrieve"

    @property
    def actions(self) -> List[str]:
        return ["read", "extract"]

    def _read_defaults(self) -> Dict[str, Any]:
        return self.config.get("defaults", {}) if isinstance(self.config, dict) else {}

    def _retrieval_root_config(self) -> Dict[str, Any]:
        kernel = self.kernel
        cfg_manager = getattr(kernel, "config_manager", None) if kernel else None
        if cfg_manager and hasattr(cfg_manager, "get"):
            raw = cfg_manager.get("retrieval", {})
            if isinstance(raw, dict):
                return raw
        return {}

    def _telemetry_enabled(self, params: Dict[str, Any]) -> bool:
        defaults = self._read_defaults()
        telemetry = self._retrieval_root_config().get("telemetry", {})
        env_enabled = os.getenv("RETRIEVAL_TELEMETRY_ENABLED")
        if isinstance(env_enabled, str) and env_enabled.strip():
            return env_enabled.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(params.get("telemetry_enabled"), bool):
            return bool(params.get("telemetry_enabled"))
        if isinstance(defaults.get("telemetry_enabled"), bool):
            return bool(defaults.get("telemetry_enabled"))
        if isinstance(telemetry, dict):
            return bool(telemetry.get("enabled", False))
        return False

    def _telemetry_level(self, params: Dict[str, Any]) -> str:
        defaults = self._read_defaults()
        telemetry = self._retrieval_root_config().get("telemetry", {})
        env_level = os.getenv("RETRIEVAL_TELEMETRY_LEVEL")
        level = str(
            env_level
            or params.get("telemetry_level")
            or defaults.get("telemetry_level")
            or (telemetry.get("level") if isinstance(telemetry, dict) else "basic")
            or "basic"
        ).strip().lower()
        return level if level in {"basic", "verbose"} else "basic"

    def _resolve_timeout_ms(self, params: Dict[str, Any]) -> int:
        defaults = self._read_defaults()
        return clamp_timeout_ms(params.get("timeout_ms") or defaults.get("timeout_ms") or 10000)

    def _resolve_connect_timeout_ms(self, params: Dict[str, Any], total_timeout_ms: int) -> int:
        defaults = self._read_defaults()
        value = (
            params.get("connect_timeout_ms")
            or defaults.get("connect_timeout_ms")
            or total_timeout_ms
        )
        return clamp_timeout_ms(value, default=total_timeout_ms)

    def _resolve_read_timeout_ms(self, params: Dict[str, Any], total_timeout_ms: int) -> int:
        defaults = self._read_defaults()
        value = (
            params.get("read_timeout_ms")
            or defaults.get("read_timeout_ms")
            or total_timeout_ms
        )
        return clamp_timeout_ms(value, default=total_timeout_ms)

    def _resolve_retries(self, params: Dict[str, Any]) -> int:
        defaults = self._read_defaults()
        return clamp_retries(params.get("retries") or defaults.get("retries") or 1)

    def _resolve_max_chars(self, params: Dict[str, Any], default: int = 12000) -> int:
        defaults = self._read_defaults()
        return clamp_max_chars(params.get("max_chars") or defaults.get("max_chars") or default)

    def _resolve_max_bytes(self, params: Dict[str, Any]) -> int:
        defaults = self._read_defaults()
        return clamp_max_bytes(params.get("max_bytes") or defaults.get("max_bytes") or 2_000_000)

    def _resolve_strip_tracking(self, params: Dict[str, Any]) -> bool:
        defaults = self._read_defaults()
        value = params.get("strip_tracking_params")
        if value is None:
            value = defaults.get("strip_tracking_params", True)
        return bool(value)

    def _resolve_respect_robots(self, params: Dict[str, Any]) -> bool:
        defaults = self._read_defaults()
        value = params.get("respect_robots")
        if value is None:
            value = defaults.get("respect_robots", False)
        return bool(value)

    def _resolve_rate_limit_per_host(self, params: Dict[str, Any]) -> float:
        defaults = self._read_defaults()
        return clamp_rate_limit(
            params.get("rate_limit_per_host") or defaults.get("rate_limit_per_host") or 0.0
        )

    def _resolve_cache_ttl_sec(self, params: Dict[str, Any]) -> int:
        defaults = self._read_defaults()
        return clamp_cache_ttl(params.get("cache_ttl_sec") or defaults.get("cache_ttl_sec") or 0)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]

        if action == "read":
            url = params.get("url")
            mode = params.get("mode", "auto")
            max_chars = self._resolve_max_chars(params, default=12000)
            timeout_ms = self._resolve_timeout_ms(params)
            connect_timeout_ms = self._resolve_connect_timeout_ms(params, timeout_ms)
            read_timeout_ms = self._resolve_read_timeout_ms(params, timeout_ms)
            retries = self._resolve_retries(params)
            max_bytes = self._resolve_max_bytes(params)
            strip_tracking_params = self._resolve_strip_tracking(params)
            respect_robots = self._resolve_respect_robots(params)
            rate_limit_per_host = self._resolve_rate_limit_per_host(params)
            cache_ttl_sec = self._resolve_cache_ttl_sec(params)
            telemetry_enabled = self._telemetry_enabled(params)
            telemetry_level = self._telemetry_level(params)

            payload = fetch_and_read(
                url=str(url or ""),
                mode=str(mode or "auto"),
                max_chars=max_chars,
                timeout_ms=timeout_ms,
                retries=retries,
                connect_timeout_ms=connect_timeout_ms,
                read_timeout_ms=read_timeout_ms,
                max_bytes=max_bytes,
                strip_tracking_params=strip_tracking_params,
                respect_robots=respect_robots,
                rate_limit_per_host=rate_limit_per_host,
                cache_ttl_sec=cache_ttl_sec,
                telemetry_enabled=telemetry_enabled,
                telemetry_level=telemetry_level,
            )

            if payload.get("ok"):
                chunk_size = clamp_chunk_size(
                    params.get("chunk_size") or self._read_defaults().get("chunk_size") or 700
                )
                chunk_overlap = clamp_chunk_overlap(
                    params.get("chunk_overlap") or self._read_defaults().get("chunk_overlap") or 100
                )
                payload["chunks"] = chunk_text(
                    payload.get("text_md") or "",
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )

            return payload

        if action == "extract":
            url = params.get("url")
            schema = params.get("schema") or []
            max_chars = self._resolve_max_chars(params, default=12000)
            timeout_ms = self._resolve_timeout_ms(params)
            connect_timeout_ms = self._resolve_connect_timeout_ms(params, timeout_ms)
            read_timeout_ms = self._resolve_read_timeout_ms(params, timeout_ms)
            retries = self._resolve_retries(params)
            max_bytes = self._resolve_max_bytes(params)
            strip_tracking_params = self._resolve_strip_tracking(params)
            respect_robots = self._resolve_respect_robots(params)
            rate_limit_per_host = self._resolve_rate_limit_per_host(params)
            telemetry_enabled = self._telemetry_enabled(params)
            telemetry_level = self._telemetry_level(params)

            return extract_structured(
                url=str(url or ""),
                schema=schema,
                max_chars=max_chars,
                timeout_ms=timeout_ms,
                retries=retries,
                connect_timeout_ms=connect_timeout_ms,
                read_timeout_ms=read_timeout_ms,
                max_bytes=max_bytes,
                strip_tracking_params=strip_tracking_params,
                respect_robots=respect_robots,
                rate_limit_per_host=rate_limit_per_host,
                telemetry_enabled=telemetry_enabled,
                telemetry_level=telemetry_level,
            )

        return error_envelope(
            provider="web.retrieve",
            error_code="UNKNOWN_ACTION",
            error_message=f"Unknown web.retrieve action: {action_id}",
            retryable=False,
            elapsed=0,
            warnings=[],
        )
