from __future__ import annotations

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
