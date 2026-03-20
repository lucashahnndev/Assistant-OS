import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.services.agent_runtime_v2 import (
    ExecutionContextEnvelope,
    GlobalScheduler,
    PolicyLayer,
    RiskModel,
    TenantGovernance,
    TenantGovernanceContext,
)
from src.core.orchestrator import AgentOrchestrator


def test_risk_model_reads_metadata_level():
    model = RiskModel()
    assert model.evaluate("browser.control.run", {"risk_level": "high"}, {}) == "high"
    assert model.evaluate("browser.control.run", {"risk_level": "invalid"}, {}) == "low"


def test_tenant_governance_returns_log_only_allow():
    governance = TenantGovernance()
    result = governance.evaluate(
        TenantGovernanceContext(tenant_id="tenant-a", agent_id="agent-a", qos_class="HIGH")
    )
    assert result["allowed"] is True
    assert result["mode"] == "log_only"
    assert result["tenant_id"] == "tenant-a"


def test_policy_layer_security_and_business_baseline_allow():
    layer = PolicyLayer()
    envelope = ExecutionContextEnvelope(
        tenant_id="tenant-z",
        session_id="s1",
        work_id="w1",
        action_id="browser.control.run",
        qos_class="NORMAL",
        risk_level="medium",
        policy_version="policy_v1",
    )
    decision = layer.evaluate(envelope, action_params={"goal": "abrir youtube"})
    payload = decision.to_dict()
    assert payload["decision"] == "allow"
    assert payload["policy_mode"] == "log_only"
    assert isinstance(payload["explanation"], dict)


def test_orchestrator_runtime_v2_governance_evaluation_returns_policy_and_tenant():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.capability_registry = None
    orchestrator.config_manager = type(
        "_Cfg",
        (),
        {"get": staticmethod(lambda key, default=None: {} if key == "runtime" else default)},
    )()
    orchestrator._runtime_v2_policy_layer = PolicyLayer()
    orchestrator._runtime_v2_risk_model = RiskModel()
    orchestrator._runtime_v2_tenant_governance = TenantGovernance()
    orchestrator._runtime_v2_scheduler_global = GlobalScheduler()

    result = orchestrator._evaluate_runtime_v2_governance(
        envelope_payload=ExecutionContextEnvelope(
            tenant_id="tenant-x",
            action_id="browser.control.run",
            risk_level="medium",
        ).to_dict(),
        action_params={"goal": "abrir browser"},
    )
    assert result["tenant_governance"]["tenant_id"] == "tenant-x"
    assert result["policy_decision"]["decision"] == "allow"
