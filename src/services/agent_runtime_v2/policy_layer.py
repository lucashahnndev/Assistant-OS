from __future__ import annotations

from typing import Any, Dict

from .contracts import DecisionExplanation, ExecutionContextEnvelope, PolicyDecisionEnvelope


class SecurityPolicyLayer:
    def evaluate(
        self,
        envelope: ExecutionContextEnvelope,
        action_params: Dict[str, Any] | None = None,
        policy_cfg: Dict[str, Any] | None = None,
    ) -> PolicyDecisionEnvelope:
        _ = action_params or {}
        cfg = policy_cfg or {}
        policy_mode = str(cfg.get("mode", "log_only") or "log_only").strip().lower()
        if policy_mode not in {"log_only", "enforce"}:
            policy_mode = "log_only"

        denied_actions = {
            str(a).strip().lower()
            for a in (cfg.get("deny_actions") or [])
            if str(a).strip()
        }
        require_approval_risks = {
            str(r).strip().lower()
            for r in (cfg.get("require_approval_risk_levels") or [])
            if str(r).strip()
        }
        constrain_risks = {
            str(r).strip().lower()
            for r in (cfg.get("allow_with_constraints_risk_levels") or [])
            if str(r).strip()
        }

        action_id = str(envelope.action_id or "").strip().lower()
        risk_level = str(envelope.risk_level or "low").strip().lower()
        decision = "allow"
        reason = "security baseline allow"
        constraints: Dict[str, Any] = {}
        rule_id = "security_default_allow"
        if action_id and action_id in denied_actions:
            decision = "deny"
            reason = "action denied by security policy"
            rule_id = "security_action_deny"
        elif risk_level in require_approval_risks:
            decision = "require_approval"
            reason = "risk level requires explicit approval"
            rule_id = "security_require_approval_by_risk"
        elif risk_level in constrain_risks:
            decision = "allow_with_constraints"
            reason = "risk level requires constrained execution"
            rule_id = "security_allow_with_constraints_by_risk"
            constraints = {"max_retries": 1, "fallback_enabled": False}

        explanation = DecisionExplanation(
            explanation_id=f"security:{rule_id}",
            decision=decision,
            action_id=envelope.action_id,
            context_summary={"tenant_id": envelope.tenant_id, "risk_level": envelope.risk_level, "policy_mode": policy_mode},
            rules_evaluated=[{"rule_id": rule_id, "matched": True}],
            risk_level=envelope.risk_level,
            reason=reason,
        )
        return PolicyDecisionEnvelope(
            decision=decision,
            policy_mode=policy_mode,
            policy_version=envelope.policy_version,
            constraints=constraints,
            explanation=explanation,
        )


class BusinessPolicyLayer:
    def evaluate(
        self,
        envelope: ExecutionContextEnvelope,
        action_params: Dict[str, Any] | None = None,
        policy_cfg: Dict[str, Any] | None = None,
    ) -> PolicyDecisionEnvelope:
        _ = action_params or {}
        cfg = policy_cfg or {}
        policy_mode = str(cfg.get("mode", "log_only") or "log_only").strip().lower()
        if policy_mode not in {"log_only", "enforce"}:
            policy_mode = "log_only"
        require_approval_actions = {
            str(a).strip().lower()
            for a in (cfg.get("require_approval_actions") or [])
            if str(a).strip()
        }
        constrained_qos = {
            str(q).strip().upper()
            for q in (cfg.get("allow_with_constraints_qos") or [])
            if str(q).strip()
        }
        action_id = str(envelope.action_id or "").strip().lower()
        qos_class = str(envelope.qos_class or "NORMAL").strip().upper()
        decision = "allow"
        reason = "business baseline allow"
        constraints: Dict[str, Any] = {}
        rule_id = "business_default_allow"
        if action_id and action_id in require_approval_actions:
            decision = "require_approval"
            reason = "action requires business approval"
            rule_id = "business_require_approval_action"
        elif qos_class in constrained_qos:
            decision = "allow_with_constraints"
            reason = "qos class requires constrained execution"
            rule_id = "business_allow_with_constraints_qos"
            constraints = {"max_parallel_actions": 1}

        explanation = DecisionExplanation(
            explanation_id=f"business:{rule_id}",
            decision=decision,
            action_id=envelope.action_id,
            context_summary={"tenant_id": envelope.tenant_id, "qos_class": envelope.qos_class, "policy_mode": policy_mode},
            rules_evaluated=[{"rule_id": rule_id, "matched": True}],
            risk_level=envelope.risk_level,
            reason=reason,
        )
        return PolicyDecisionEnvelope(
            decision=decision,
            policy_mode=policy_mode,
            policy_version=envelope.policy_version,
            constraints=constraints,
            explanation=explanation,
        )


class PolicyMerger:
    """Security-first precedence with explicit decision ordering."""

    @staticmethod
    def merge(security: PolicyDecisionEnvelope, business: PolicyDecisionEnvelope) -> PolicyDecisionEnvelope:
        order = {"deny": 4, "require_approval": 3, "allow_with_constraints": 2, "allow": 1}
        sec_score = order.get(str(security.decision), 1)
        biz_score = order.get(str(business.decision), 1)
        chosen = security if sec_score >= biz_score else business
        if str(security.decision) == "deny":
            chosen = security
        constraints = dict(security.constraints)
        constraints.update(business.constraints)
        return PolicyDecisionEnvelope(
            decision=str(chosen.decision),
            policy_mode=str(security.policy_mode or business.policy_mode or "log_only"),
            policy_version=security.policy_version or business.policy_version,
            constraints=constraints,
            explanation=chosen.explanation or business.explanation or security.explanation,
        )


class PolicyLayer:
    def __init__(self) -> None:
        self.security = SecurityPolicyLayer()
        self.business = BusinessPolicyLayer()
        self.merger = PolicyMerger()

    def evaluate(
        self,
        envelope: ExecutionContextEnvelope,
        action_params: Dict[str, Any] | None = None,
        policy_cfg: Dict[str, Any] | None = None,
    ) -> PolicyDecisionEnvelope:
        sec = self.security.evaluate(envelope, action_params=action_params, policy_cfg=policy_cfg)
        biz = self.business.evaluate(envelope, action_params=action_params, policy_cfg=policy_cfg)
        return self.merger.merge(sec, biz)
