from __future__ import annotations

import threading
from typing import Any, Dict, Tuple


class RuntimeCostBudget:
    """Tracks per-work and per-tenant action/call budgets."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._work_usage: Dict[str, Dict[str, int]] = {}
        self._tenant_usage: Dict[str, Dict[str, int]] = {}

    def consume(
        self,
        *,
        tenant_id: str,
        work_id: str,
        cfg: Dict[str, Any] | None = None,
        action_units: int = 1,
        mcp_calls: int = 0,
    ) -> Dict[str, Any]:
        policy = cfg or {}
        max_actions_per_goal = max(1, int(policy.get("max_actions_per_goal", 120) or 120))
        max_mcp_calls_per_step = max(1, int(policy.get("max_mcp_calls_per_step", 15) or 15))
        max_actions_per_tenant_window = max(1, int(policy.get("max_actions_per_tenant_window", 1200) or 1200))

        tenant_key = str(tenant_id or "default").strip() or "default"
        work_key = str(work_id or "")

        with self._lock:
            work_state = dict(self._work_usage.get(work_key, {"actions": 0, "mcp_calls": 0}))
            tenant_state = dict(self._tenant_usage.get(tenant_key, {"actions": 0}))

            next_work_actions = int(work_state.get("actions", 0)) + int(action_units)
            next_work_mcp_calls = int(mcp_calls)
            next_tenant_actions = int(tenant_state.get("actions", 0)) + int(action_units)

            if work_key and next_work_actions > max_actions_per_goal:
                return {
                    "allowed": False,
                    "reason": "max_actions_per_goal_exceeded",
                    "tenant_id": tenant_key,
                    "work_id": work_key,
                }
            if next_work_mcp_calls > max_mcp_calls_per_step:
                return {
                    "allowed": False,
                    "reason": "max_mcp_calls_per_step_exceeded",
                    "tenant_id": tenant_key,
                    "work_id": work_key,
                }
            if next_tenant_actions > max_actions_per_tenant_window:
                return {
                    "allowed": False,
                    "reason": "max_actions_per_tenant_window_exceeded",
                    "tenant_id": tenant_key,
                    "work_id": work_key,
                }

            if work_key:
                self._work_usage[work_key] = {
                    "actions": next_work_actions,
                    "mcp_calls": next_work_mcp_calls,
                }
            self._tenant_usage[tenant_key] = {"actions": next_tenant_actions}

        return {
            "allowed": True,
            "reason": "ok",
            "tenant_id": tenant_key,
            "work_id": work_key,
            "usage": {
                "work_actions": next_work_actions if work_key else 0,
                "work_mcp_calls": next_work_mcp_calls,
                "tenant_actions": next_tenant_actions,
            },
            "limits": {
                "max_actions_per_goal": max_actions_per_goal,
                "max_mcp_calls_per_step": max_mcp_calls_per_step,
                "max_actions_per_tenant_window": max_actions_per_tenant_window,
            },
        }
