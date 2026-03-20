import sys
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.services.agent_runtime_v2 import PolicyRolloutEngine
from src.core.orchestrator import AgentOrchestrator


class _Cfg:
    def __init__(self, base_data_dir: str):
        self.base_data_dir = base_data_dir

    def get(self, key, default=None):
        return default


def test_rollout_lifecycle_transitions_and_invalid_path():
    with tempfile.TemporaryDirectory() as tmp:
        engine = PolicyRolloutEngine(config_manager=_Cfg(tmp))
        created = engine.create_draft(policy_id="policy-v2", policy_cfg={"mode": "enforce"})
        assert created["ok"] is True

        simulated = engine.mark_simulated(policy_id="policy-v2", simulation_result={"changed_events": 3})
        assert simulated["ok"] is True
        assert simulated["policy"]["state"] == "simulated"

        canary = engine.start_canary(policy_id="policy-v2", tenant_ids=["tenant-a"], rollout_percent=10)
        assert canary["ok"] is True
        assert canary["policy"]["state"] == "canary"

        active = engine.promote_active(policy_id="policy-v2", tenant_ids=["tenant-a"])
        assert active["ok"] is True
        assert active["policy"]["state"] == "active"

        invalid = engine.mark_simulated(policy_id="policy-v2", simulation_result={})
        assert invalid["ok"] is False
        assert invalid["error_code"] == "INVALID_STATE_TRANSITION"


def test_rollout_resolve_effective_policy_for_tenant_and_global():
    with tempfile.TemporaryDirectory() as tmp:
        engine = PolicyRolloutEngine(config_manager=_Cfg(tmp))
        engine.create_draft(policy_id="global-p", policy_cfg={"mode": "enforce", "deny_actions": ["x"]})
        engine.mark_simulated(policy_id="global-p", simulation_result={})
        engine.start_canary(policy_id="global-p", tenant_ids=[], rollout_percent=100)
        engine.promote_active(policy_id="global-p")

        cfg = engine.resolve_effective_policy(tenant_id="tenant-any", default_policy_cfg={"mode": "log_only"})
        assert cfg.get("mode") == "enforce"

        engine.create_draft(policy_id="tenant-p", policy_cfg={"mode": "enforce", "deny_actions": ["browser.control.run"]})
        engine.mark_simulated(policy_id="tenant-p", simulation_result={})
        engine.start_canary(policy_id="tenant-p", tenant_ids=["tenant-a"], rollout_percent=10)
        cfg_tenant = engine.resolve_effective_policy(tenant_id="tenant-a", default_policy_cfg={"mode": "log_only"})
        assert cfg_tenant.get("deny_actions") == ["browser.control.run"]


def test_rollout_auto_abort_canary_triggers_rollback():
    with tempfile.TemporaryDirectory() as tmp:
        engine = PolicyRolloutEngine(config_manager=_Cfg(tmp))
        engine.create_draft(policy_id="abort-p", policy_cfg={"mode": "enforce"})
        engine.mark_simulated(policy_id="abort-p", simulation_result={})
        engine.start_canary(policy_id="abort-p", tenant_ids=["tenant-a"], rollout_percent=5)

        abort = engine.evaluate_canary_regression(
            policy_id="abort-p",
            metrics={"error_rate": 0.9, "latency_increase": 0.1},
            thresholds={"max_error_rate": 0.2, "max_latency_increase": 0.5},
        )
        assert abort["abort"] is True
        policy = engine.get_policy("abort-p")
        assert policy.get("state") == "rolled_back"


def test_orchestrator_rollout_helpers_resolve_effective_policy_cfg():
    with tempfile.TemporaryDirectory() as tmp:
        orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
        orchestrator._runtime_v2_policy_rollout = PolicyRolloutEngine(config_manager=_Cfg(tmp))

        create = orchestrator._runtime_v2_policy_rollout_create_draft(
            policy_id="p1",
            policy_cfg={"mode": "enforce", "deny_actions": ["browser.control.run"]},
            created_by="test",
        )
        assert create["ok"] is True
        orchestrator._runtime_v2_policy_rollout_mark_simulated(policy_id="p1", simulation_result={})
        orchestrator._runtime_v2_policy_rollout_start_canary(policy_id="p1", tenant_ids=["tenant-a"], rollout_percent=10)
        orchestrator._runtime_v2_policy_rollout_promote_active(policy_id="p1", tenant_ids=["tenant-a"])

        cfg = orchestrator._resolve_runtime_v2_effective_policy_cfg(
            tenant_id="tenant-a",
            v2_cfg={
                "policy": {"mode": "log_only"},
                "policy_rollout": {"enabled": True},
            },
        )
        assert cfg.get("deny_actions") == ["browser.control.run"]
