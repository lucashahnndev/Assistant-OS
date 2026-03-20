import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.core.orchestrator import AgentOrchestrator
from src.services.agent_runtime_v2 import ExecutionContextEnvelope, PolicyLayer


def test_policy_layer_supports_decision_variants_with_explanation():
    layer = PolicyLayer()
    envelope = ExecutionContextEnvelope(
        tenant_id="tenant-a",
        action_id="browser.control.run",
        risk_level="high",
        qos_class="LOW",
        policy_version="policy_v3",
    )
    decision = layer.evaluate(
        envelope,
        action_params={"goal": "x"},
        policy_cfg={
            "mode": "enforce",
            "require_approval_risk_levels": ["critical"],
            "allow_with_constraints_risk_levels": ["high"],
            "allow_with_constraints_qos": ["LOW"],
        },
    ).to_dict()

    assert decision["decision"] == "allow_with_constraints"
    assert decision["policy_mode"] == "enforce"
    assert isinstance(decision.get("explanation"), dict)
    assert str((decision.get("explanation") or {}).get("reason") or "").strip() != ""


def test_orchestrator_policy_gate_blocks_deny_in_enforce_mode():
    exec_context = {
        "runtime_v2_governance": {
            "policy_decision": {
                "decision": "deny",
                "policy_mode": "enforce",
                "constraints": {},
                "explanation": {
                    "explanation_id": "security:security_action_deny",
                    "reason": "action denied by security policy",
                },
            }
        }
    }
    blocked = AgentOrchestrator._apply_runtime_v2_policy_gate(exec_context, "browser.control.run")
    assert isinstance(blocked, dict)
    assert blocked.get("error_code") == "POLICY_DENIED"
    assert isinstance(blocked.get("policy_decision_envelope"), dict)


def test_runtime_v2_receipt_carries_decision_explanation_fields():
    receipt = AgentOrchestrator._build_runtime_v2_receipt(
        exec_context={
            "execution_context_envelope": {
                "tenant_id": "tenant-r",
                "qos_class": "HIGH",
                "risk_level": "medium",
                "policy_version": "policy_v3",
            },
            "runtime_v2_governance": {
                "policy_decision": {
                    "decision": "require_approval",
                    "policy_mode": "enforce",
                    "explanation": {
                        "explanation_id": "business:business_require_approval_action",
                        "reason": "action requires business approval",
                    },
                }
            },
        },
        latency_ms=55,
    )
    assert receipt["policy_decision"] == "require_approval"
    assert receipt["policy_mode"] == "enforce"
    assert receipt["decision_explanation_id"] == "business:business_require_approval_action"
    assert receipt["decision_reason"] == "action requires business approval"
