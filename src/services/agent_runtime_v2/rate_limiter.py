from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple


class RuntimeRateLimiter:
    """In-memory fixed-window limiter for tenant/agent throughput + parallelism."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._agent_windows: Dict[str, Tuple[float, int]] = {}
        self._tenant_windows: Dict[str, Tuple[float, int]] = {}
        self._agent_parallel: Dict[str, int] = {}

    @staticmethod
    def _window_check(window: Tuple[float, int] | None, now: float, limit: int, interval_s: int) -> Tuple[bool, Tuple[float, int]]:
        if limit <= 0:
            return True, (now, 0)
        if not window:
            return True, (now, 1)
        start_ts, count = window
        if now - float(start_ts) >= float(interval_s):
            return True, (now, 1)
        if int(count) >= int(limit):
            return False, (start_ts, count)
        return True, (start_ts, count + 1)

    def acquire(self, *, tenant_id: str, agent_id: str, cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
        policy = cfg or {}
        interval_s = max(1, int(policy.get("window_seconds", 60) or 60))
        max_per_agent = max(1, int(policy.get("max_actions_per_minute_per_agent", 60) or 60))
        max_per_tenant = max(1, int(policy.get("max_actions_per_minute_per_tenant", 300) or 300))
        max_parallel_agent = max(1, int(policy.get("max_parallel_actions_per_agent", 2) or 2))

        tenant_key = str(tenant_id or "default").strip() or "default"
        agent_key = str(agent_id or "main_orchestrator").strip() or "main_orchestrator"
        now = time.time()

        with self._lock:
            agent_ok, agent_next = self._window_check(
                self._agent_windows.get(agent_key),
                now,
                max_per_agent,
                interval_s,
            )
            if not agent_ok:
                return {
                    "allowed": False,
                    "reason": "agent_actions_per_minute_exceeded",
                    "tenant_id": tenant_key,
                    "agent_id": agent_key,
                }

            tenant_ok, tenant_next = self._window_check(
                self._tenant_windows.get(tenant_key),
                now,
                max_per_tenant,
                interval_s,
            )
            if not tenant_ok:
                return {
                    "allowed": False,
                    "reason": "tenant_actions_per_minute_exceeded",
                    "tenant_id": tenant_key,
                    "agent_id": agent_key,
                }

            current_parallel = int(self._agent_parallel.get(agent_key, 0))
            if current_parallel >= max_parallel_agent:
                return {
                    "allowed": False,
                    "reason": "agent_parallel_limit_exceeded",
                    "tenant_id": tenant_key,
                    "agent_id": agent_key,
                }

            self._agent_windows[agent_key] = agent_next
            self._tenant_windows[tenant_key] = tenant_next
            self._agent_parallel[agent_key] = current_parallel + 1

        return {
            "allowed": True,
            "reason": "ok",
            "tenant_id": tenant_key,
            "agent_id": agent_key,
            "lease": {"agent_id": agent_key},
            "limits": {
                "max_actions_per_minute_per_agent": max_per_agent,
                "max_actions_per_minute_per_tenant": max_per_tenant,
                "max_parallel_actions_per_agent": max_parallel_agent,
            },
        }

    def release(self, lease: Optional[Dict[str, Any]]) -> None:
        if not isinstance(lease, dict):
            return
        agent_key = str(lease.get("agent_id", "")).strip()
        if not agent_key:
            return
        with self._lock:
            current = int(self._agent_parallel.get(agent_key, 0))
            if current <= 1:
                self._agent_parallel.pop(agent_key, None)
            else:
                self._agent_parallel[agent_key] = current - 1
