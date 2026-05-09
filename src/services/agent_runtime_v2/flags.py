from __future__ import annotations

import os
from typing import Any, Dict


def is_agent_runtime_v2_enabled(config_manager: Any) -> bool:
    if not config_manager or not hasattr(config_manager, "get"):
        return False
    runtime_cfg = config_manager.get("runtime", {})
    if not isinstance(runtime_cfg, dict):
        return False
    return bool(runtime_cfg.get("agent_runtime_v2_enabled", False))


def get_agent_runtime_v2_config(config_manager: Any) -> Dict[str, Any]:
    if not config_manager or not hasattr(config_manager, "get"):
        return {}
    runtime_cfg = config_manager.get("runtime", {})
    if not isinstance(runtime_cfg, dict):
        return {}
    return dict(runtime_cfg.get("agent_runtime_v2", {}) or {})


def _read_bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def is_strict_mode_enabled(config_manager: Any) -> bool:
    runtime_cfg = get_agent_runtime_v2_config(config_manager)
    if "strict_mode" in runtime_cfg:
        return bool(runtime_cfg.get("strict_mode", False))
    return _read_bool_env("STRICT_MODE", default=False)


def is_paranoid_mode_enabled(config_manager: Any) -> bool:
    runtime_cfg = get_agent_runtime_v2_config(config_manager)
    if "paranoid_mode" in runtime_cfg:
        return bool(runtime_cfg.get("paranoid_mode", False))
    return _read_bool_env("PARANOID_MODE", default=False)


def get_max_provider_attempts_per_turn(config_manager: Any) -> int:
    runtime_cfg = get_agent_runtime_v2_config(config_manager)
    value = runtime_cfg.get("max_provider_attempts_per_turn", 2)
    try:
        return max(1, int(value))
    except Exception:
        return 2


def get_max_same_provider_retries(config_manager: Any) -> int:
    runtime_cfg = get_agent_runtime_v2_config(config_manager)
    value = runtime_cfg.get("max_same_provider_retries", 0)
    try:
        return max(0, int(value))
    except Exception:
        return 0
