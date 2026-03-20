import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.core.orchestrator import AgentOrchestrator
from src.core.resolution.action_plan import ActionPlan
from src.services.agent_runtime_v2 import PolicyLayer, RiskModel, TenantGovernance


class _FakeRegistry:
    def get_action_metadata(self, action_id):
        if action_id == "browser.control.run":
            return {"risk_level": "medium"}
        return {}


class _FakeConfigManager:
    def __init__(self, payload):
        self._payload = payload

    def get(self, key, default=None):
        return self._payload.get(key, default)


def _make_orchestrator():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.capability_registry = _FakeRegistry()
    orchestrator.config_manager = _FakeConfigManager(
        {
            "runtime": {
                "agent_runtime_v2_enabled": True,
                "agent_runtime_v2": {
                    "runtime_version": "runtime_v2.1",
                    "planner_version": "planner_v2.1",
                    "policy_version": "policy_v2.1",
                },
            }
        }
    )
    orchestrator._runtime_v2_policy_layer = PolicyLayer()
    orchestrator._runtime_v2_risk_model = RiskModel()
    orchestrator._runtime_v2_tenant_governance = TenantGovernance()
    orchestrator._touches = []

    def _touch(work_id, patch):
        orchestrator._touches.append((work_id, patch))

    orchestrator._touch_work_context = _touch
    return orchestrator


def test_execution_context_envelope_includes_delegation_contract_and_qos():
    orchestrator = _make_orchestrator()
    plan = ActionPlan(
        action_id="browser.control.run",
        metadata={
            "qos_class": "HIGH",
            "tenant_id": "tenant-p1",
            "delegation_contract": {
                "delegation_id": "deleg-123",
                "parent_agent_id": "agent-main",
                "child_agent_id": "agent-sub",
                "delegated_goal": "finalizar checkout",
            },
        },
    )

    envelope = orchestrator._build_execution_context_envelope(
        plan=plan,
        context=None,
        session_id="sess-1",
        work_id="work-1",
    )
    assert envelope["tenant_id"] == "tenant-p1"
    assert envelope["qos_class"] == "HIGH"
    assert envelope["policy_version"] == "policy_v2.1"
    assert envelope["delegation"]["delegation_id"] == "deleg-123"


def test_execution_context_envelope_auto_delegates_browser_run_when_missing_contract():
    orchestrator = _make_orchestrator()
    plan = ActionPlan(
        action_id="browser.control.run",
        args={"goal": "abrir https://example.com"},
        metadata={"tenant_id": "tenant-p1"},
    )
    envelope = orchestrator._build_execution_context_envelope(
        plan=plan,
        context=None,
        session_id="sess-2",
        work_id="work-2",
    )
    delegation = envelope.get("delegation") or {}
    assert str(delegation.get("delegation_id") or "").startswith("auto_browser_")
    assert delegation.get("child_agent_id") == "browser_subagent_executor"
    assert delegation.get("delegated_goal") == "abrir https://example.com"


def test_attach_runtime_v2_receipt_enriches_result_and_work_context():
    orchestrator = _make_orchestrator()
    exec_context = {
        "execution_context_envelope": {
            "tenant_id": "tenant-z",
            "qos_class": "CRITICAL",
            "risk_level": "high",
            "policy_version": "policy_v2.1",
        },
        "runtime_v2_governance": {
            "policy_decision": {"decision": "allow_with_constraints"}
        },
    }
    result = orchestrator._attach_runtime_v2_receipt(
        result={"ok": True, "status": "success"},
        exec_context=exec_context,
        latency_ms=321,
        work_id="work-9",
    )
    receipt = result.get("runtime_v2_receipt") or {}
    assert receipt.get("tenant_id") == "tenant-z"
    assert receipt.get("qos_class") == "CRITICAL"
    assert receipt.get("risk_level") == "high"
    assert receipt.get("policy_version") == "policy_v2.1"
    assert receipt.get("policy_decision") == "allow_with_constraints"
    assert receipt.get("latency_ms") == 321
    assert orchestrator._touches and orchestrator._touches[-1][0] == "work-9"
