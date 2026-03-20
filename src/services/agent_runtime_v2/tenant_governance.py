from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class TenantGovernanceContext:
    tenant_id: str
    agent_id: str = ""
    qos_class: str = "NORMAL"


class TenantGovernance:
    """Phase scaffolding: tenant governance hooks for quotas/fairness/budgets."""

    def evaluate(self, context: TenantGovernanceContext, policy_cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
        cfg = policy_cfg or {}
        return {
            "tenant_id": context.tenant_id or "default",
            "agent_id": context.agent_id,
            "qos_class": context.qos_class,
            "quota_profile": cfg.get("quota_profile", "default"),
            "allowed": True,
            "mode": "log_only",
        }
