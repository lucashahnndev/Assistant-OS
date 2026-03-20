from __future__ import annotations

from typing import Any, Dict

from .contracts import DecisionExplanation, ExecutionContextEnvelope, PolicyDecisionEnvelope


class SecurityPolicyLayer:
    def evaluate(self, envelope: ExecutionContextEnvelope, action_params: Dict[str, Any] | None = None) -> PolicyDecisionEnvelope:
        _ = action_params or {}
        explanation = DecisionExplanation(
            explanation_id="security:allow_default",
            decision="allow",
            action_id=envelope.action_id,
            context_summary={"tenant_id": envelope.tenant_id, "risk_level": envelope.risk_level},
            rules_evaluated=[{"rule_id": "security_default_allow", "matched": True}],
            risk_level=envelope.risk_level,
            reason="security baseline allow (phase log-only)",
        )
        return PolicyDecisionEnvelope(
            decision="allow",
            policy_mode="log_only",
            policy_version=envelope.policy_version,
            constraints={},
            explanation=explanation,
        )


class BusinessPolicyLayer:
    def evaluate(self, envelope: ExecutionContextEnvelope, action_params: Dict[str, Any] | None = None) -> PolicyDecisionEnvelope:
        _ = action_params or {}
        explanation = DecisionExplanation(
            explanation_id="business:allow_default",
            decision="allow",
            action_id=envelope.action_id,
            context_summary={"tenant_id": envelope.tenant_id, "qos_class": envelope.qos_class},
            rules_evaluated=[{"rule_id": "business_default_allow", "matched": True}],
            risk_level=envelope.risk_level,
            reason="business baseline allow (phase log-only)",
        )
        return PolicyDecisionEnvelope(
            decision="allow",
            policy_mode="log_only",
            policy_version=envelope.policy_version,
            constraints={},
            explanation=explanation,
        )


class PolicyMerger:
    """Security-first precedence: deny from security always wins."""

    @staticmethod
    def merge(security: PolicyDecisionEnvelope, business: PolicyDecisionEnvelope) -> PolicyDecisionEnvelope:
        if security.decision == "deny":
            return security
        if business.decision == "deny":
            # business deny remains deny, but cannot override security constraints to weaken security.
            return business
        constraints = dict(security.constraints)
        constraints.update(business.constraints)
        return PolicyDecisionEnvelope(
            decision="allow",
            policy_mode="log_only",
            policy_version=security.policy_version or business.policy_version,
            constraints=constraints,
            explanation=business.explanation or security.explanation,
        )


class PolicyLayer:
    def __init__(self) -> None:
        self.security = SecurityPolicyLayer()
        self.business = BusinessPolicyLayer()
        self.merger = PolicyMerger()

    def evaluate(self, envelope: ExecutionContextEnvelope, action_params: Dict[str, Any] | None = None) -> PolicyDecisionEnvelope:
        sec = self.security.evaluate(envelope, action_params=action_params)
        biz = self.business.evaluate(envelope, action_params=action_params)
        return self.merger.merge(sec, biz)
