import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.core.orchestrator import AgentOrchestrator
from src.services.agent_runtime_v2 import (
    ExecutionContextEnvelope,
    GlobalScheduler,
    PolicyLayer,
    RiskModel,
    RuntimeCostBudget,
    RuntimeRateLimiter,
    RuntimeV2Observability,
    TenantGovernance,
    is_agent_runtime_v2_enabled,
)


class _Cfg:
    def __init__(self, runtime_cfg):
        self._runtime_cfg = runtime_cfg
        self.base_data_dir = str(ROOT / "data")

    def get(self, key, default=None):
        if key == "runtime":
            return self._runtime_cfg
        return default


class _Plan:
    def __init__(self, action_id: str, metadata=None):
        self.action_id = action_id
        self.metadata = metadata if isinstance(metadata, dict) else {}


def _runtime_cfg_enabled():
    return {
        "agent_runtime_v2_enabled": True,
        "agent_runtime_v2": {
            "policy_mode": "enforce",
            "policy": {
                "mode": "enforce",
            },
            "governance": {
                "rate_limit": {
                    "window_seconds": 60,
                    "max_actions_per_minute_per_agent": 10,
                    "max_actions_per_minute_per_tenant": 50,
                    "max_parallel_actions_per_agent": 2,
                },
                "cost_budget": {
                    "max_actions_per_goal": 10,
                    "max_mcp_calls_per_step": 5,
                    "max_actions_per_tenant_window": 100,
                },
            },
            "observability": {
                "enabled": True,
                "event_log": "runtime_v2/governance_events.jsonl",
            },
        },
    }


def test_operational_smoke_with_runtime_v2_enabled_end_to_end_governance_path():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.capability_registry = None
    orchestrator.config_manager = _Cfg(_runtime_cfg_enabled())
    orchestrator._runtime_v2_policy_layer = PolicyLayer()
    orchestrator._runtime_v2_risk_model = RiskModel()
    orchestrator._runtime_v2_tenant_governance = TenantGovernance()
    orchestrator._runtime_v2_scheduler_global = GlobalScheduler()
    orchestrator._runtime_v2_rate_limiter = RuntimeRateLimiter()
    orchestrator._runtime_v2_cost_budget = RuntimeCostBudget()
    orchestrator._runtime_v2_observability = RuntimeV2Observability(orchestrator.config_manager)

    touched = []

    def _fake_touch(work_id, patch):
        touched.append((work_id, patch))

    orchestrator._touch_work_context = _fake_touch

    exec_context = {
        "session_id": "session-smoke-1",
        "execution_context_envelope": ExecutionContextEnvelope(
            tenant_id="tenant-smoke",
            agent_id="agent-smoke",
            session_id="session-smoke-1",
            work_id="work-smoke-1",
            action_id="browser.control.run",
            qos_class="HIGH",
            risk_level="medium",
            policy_version="policy_v1",
        ).to_dict(),
    }
    exec_context["runtime_v2_governance"] = orchestrator._evaluate_runtime_v2_governance(
        envelope_payload=exec_context["execution_context_envelope"],
        action_params={"goal": "abrir pagina"},
    )

    op_block = orchestrator._apply_runtime_v2_operational_gate(exec_context=exec_context, work_id="work-smoke-1")
    assert op_block is None

    policy_block = orchestrator._apply_runtime_v2_policy_gate(exec_context, "browser.control.run")
    assert policy_block is None

    result = orchestrator._attach_runtime_v2_receipt(
        result={"ok": True, "status": "success", "data": {"ok": True}},
        exec_context=exec_context,
        latency_ms=12,
        work_id="work-smoke-1",
    )
    receipt = result.get("runtime_v2_receipt") or {}
    assert receipt.get("engine") == "agent_runtime_v2"
    assert receipt.get("tenant_id") == "tenant-smoke"
    assert receipt.get("policy_decision") in {"allow", "allow_with_constraints", "require_approval", "deny"}

    orchestrator._record_runtime_v2_observability(
        exec_context=exec_context,
        action_id="browser.control.run",
        action_args={"goal": "abrir pagina"},
        result_status="success",
        result_reason="ok",
        latency_ms=12,
        loop_index=1,
        work_id="work-smoke-1",
    )
    assert len(touched) >= 2


def test_fast_rollback_path_flag_off_keeps_runtime_v2_disabled_in_envelope_metadata():
    cfg = _Cfg(
        {
            "agent_runtime_v2_enabled": False,
            "agent_runtime_v2": {
                "policy_mode": "log_only",
            },
        }
    )
    assert is_agent_runtime_v2_enabled(cfg) is False

    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.config_manager = cfg
    orchestrator.capability_registry = None

    envelope = orchestrator._build_execution_context_envelope(
        plan=_Plan("browser.control.run", metadata={"tenant_id": "tenant-off"}),
        context=None,
        session_id="session-off-1",
        work_id="work-off-1",
    )
    assert envelope["metadata"]["runtime_v2_enabled"] is False
