import sys
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.core.orchestrator import AgentOrchestrator
from src.core.resolution.action_plan import ActionPlan
from src.services.agent_runtime_v2 import ExecutionContextEnvelope, is_agent_runtime_v2_enabled


class _FakeConfigManager:
    def __init__(self, payload):
        self._payload = payload

    def get(self, key, default=None):
        return self._payload.get(key, default)


class _FakeRegistry:
    def get_action_metadata(self, action_id):
        if action_id == "browser.control.run":
            return {"risk_level": "medium"}
        return {}


def test_flag_defaults_to_false_when_runtime_block_missing():
    cfg = _FakeConfigManager({})
    assert is_agent_runtime_v2_enabled(cfg) is False


def test_execution_context_envelope_to_dict_is_stable():
    env = ExecutionContextEnvelope(
        tenant_id="tenant-1",
        session_id="s1",
        work_id="w1",
        action_id="browser.control.run",
        qos_class="NORMAL",
        risk_level="medium",
    )
    payload = env.to_dict()
    assert payload["tenant_id"] == "tenant-1"
    assert payload["qos_class"] == "NORMAL"
    assert payload["risk_level"] == "medium"


def test_orchestrator_builds_envelope_with_runtime_flag_and_metadata():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.capability_registry = _FakeRegistry()
    orchestrator.config_manager = _FakeConfigManager(
        {
            "runtime": {
                "agent_runtime_v2_enabled": True,
            }
        }
    )
    plan = ActionPlan(action_id="browser.control.run")
    principal = SimpleNamespace(group_id="tenant-x")

    envelope = orchestrator._build_execution_context_envelope(
        plan=plan,
        context=principal,
        session_id="session-a",
        work_id="work-a",
    )

    assert envelope["tenant_id"] == "tenant-x"
    assert envelope["action_id"] == "browser.control.run"
    assert envelope["risk_level"] == "medium"
    assert envelope["metadata"]["runtime_v2_enabled"] is True
