from __future__ import annotations

from typing import Any, Dict


class RiskModel:
    """Phase scaffolding: resolves runtime risk from action metadata + context."""

    def evaluate(self, action_id: str, action_metadata: Dict[str, Any] | None = None, context: Dict[str, Any] | None = None) -> str:
        _ = context or {}
        meta = action_metadata or {}
        level = str(meta.get("risk_level", "low") or "low").strip().lower()
        if level not in {"low", "medium", "high", "critical"}:
            return "low"
        return level
