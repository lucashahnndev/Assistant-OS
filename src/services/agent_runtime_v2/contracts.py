from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DelegationContract:
    delegation_id: str = ""
    parent_agent_id: str = ""
    child_agent_id: str = ""
    delegated_goal: str = ""
    allowed_scopes: List[str] = field(default_factory=list)
    inherited_budget: Dict[str, Any] = field(default_factory=dict)
    success_criteria: List[str] = field(default_factory=list)
    cancellation_criteria: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delegation_id": self.delegation_id,
            "parent_agent_id": self.parent_agent_id,
            "child_agent_id": self.child_agent_id,
            "delegated_goal": self.delegated_goal,
            "allowed_scopes": list(self.allowed_scopes),
            "inherited_budget": dict(self.inherited_budget),
            "success_criteria": list(self.success_criteria),
            "cancellation_criteria": list(self.cancellation_criteria),
        }


@dataclass
class ExecutionContextEnvelope:
    envelope_version: str = "1.0"
    environment_mode: str = "production"
    tenant_id: str = "default"
    agent_id: str = ""
    session_id: str = ""
    work_id: str = ""
    action_id: str = ""
    qos_class: str = "NORMAL"
    risk_level: str = "low"
    runtime_version: str = "runtime_v1"
    planner_version: str = "planner_v1"
    policy_version: str = "policy_v1"
    delegation: Optional[DelegationContract] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "envelope_version": self.envelope_version,
            "environment_mode": self.environment_mode,
            "tenant_id": self.tenant_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "work_id": self.work_id,
            "action_id": self.action_id,
            "qos_class": self.qos_class,
            "risk_level": self.risk_level,
            "runtime_version": self.runtime_version,
            "planner_version": self.planner_version,
            "policy_version": self.policy_version,
            "metadata": dict(self.metadata),
        }
        if self.delegation:
            payload["delegation"] = self.delegation.to_dict()
        else:
            payload["delegation"] = None
        return payload


@dataclass
class DecisionExplanation:
    explanation_id: str = ""
    decision: str = "allow"
    action_id: str = ""
    context_summary: Dict[str, Any] = field(default_factory=dict)
    rules_evaluated: List[Dict[str, Any]] = field(default_factory=list)
    risk_level: str = "low"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "explanation_id": self.explanation_id,
            "decision": self.decision,
            "action_id": self.action_id,
            "context_summary": dict(self.context_summary),
            "rules_evaluated": list(self.rules_evaluated),
            "risk_level": self.risk_level,
            "reason": self.reason,
        }


@dataclass
class PolicyDecisionEnvelope:
    decision: str = "allow"
    policy_mode: str = "log_only"
    policy_version: str = "policy_v1"
    constraints: Dict[str, Any] = field(default_factory=dict)
    explanation: Optional[DecisionExplanation] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "policy_mode": self.policy_mode,
            "policy_version": self.policy_version,
            "constraints": dict(self.constraints),
            "explanation": self.explanation.to_dict() if self.explanation else None,
        }
