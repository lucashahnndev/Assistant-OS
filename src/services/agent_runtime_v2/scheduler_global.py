from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Deque, Dict, List


class GlobalScheduler:
    """Fairness helper using tenant round-robin and QoS weighting."""

    QOS_WEIGHT = {
        "CRITICAL": 4,
        "HIGH": 3,
        "NORMAL": 2,
        "LOW": 1,
    }

    def select_fair(self, jobs: List[Dict[str, Any]], slots: int) -> List[Dict[str, Any]]:
        if slots <= 0 or not jobs:
            return []

        grouped: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)
        tenant_order: List[str] = []
        for row in sorted(jobs, key=self._sort_key, reverse=True):
            tenant = str(row.get("tenant_id", "default") or "default").strip() or "default"
            if tenant not in grouped:
                tenant_order.append(tenant)
            grouped[tenant].append(row)

        selected: List[Dict[str, Any]] = []
        while len(selected) < slots and tenant_order:
            next_order: List[str] = []
            for tenant in tenant_order:
                bucket = grouped.get(tenant)
                if not bucket:
                    continue
                job = bucket.popleft()
                selected.append(job)
                if len(selected) >= slots:
                    break
                if bucket:
                    next_order.append(tenant)
            tenant_order = next_order

        return selected

    def _sort_key(self, row: Dict[str, Any]) -> tuple:
        qos = str(row.get("qos_class", "NORMAL") or "NORMAL").strip().upper()
        weight = int(self.QOS_WEIGHT.get(qos, 2))
        waiting = float(row.get("waiting_ms", 0) or 0)
        aging = min(waiting / 1000.0, 300.0)
        return (weight + aging, waiting)
