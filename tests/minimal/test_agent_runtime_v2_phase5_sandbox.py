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


class _FakeRegistry:
    def __init__(self, side_effect="idempotent"):
        self._side_effect = side_effect

    def get_action_metadata(self, action_id):
        _ = action_id
        return {"side_effect": self._side_effect, "risk_level": "medium"}


class _FakeConfig:
    def __init__(self, runtime_payload):
        self.runtime_payload = runtime_payload

    def get(self, key, default=None):
        if key == "runtime":
            return self.runtime_payload
        return default


def _mk_orchestrator(runtime_payload, side_effect="idempotent"):
    o = AgentOrchestrator.__new__(AgentOrchestrator)
    o.capability_registry = _FakeRegistry(side_effect=side_effect)
    o.config_manager = _FakeConfig(runtime_payload)
    return o


def test_envelope_resolves_sandbox_mode_by_tenant_config():
    orchestrator = _mk_orchestrator(
        {
            "agent_runtime_v2_enabled": True,
            "agent_runtime_v2": {
                "sandbox": {
                    "tenant_ids": ["tenant-sbx"],
                    "default_profile_id": "profile-default",
                    "profile_by_tenant": {"tenant-sbx": "profile-sbx"},
                }
            },
        }
    )
    plan = ActionPlan(action_id="browser.control.run", metadata={"tenant_id": "tenant-sbx"})
    envelope = orchestrator._build_execution_context_envelope(
        plan=plan,
        context=None,
        session_id="s1",
        work_id="w1",
    )
    assert envelope["environment_mode"] == "sandbox"
    assert envelope["sandbox_profile_id"] == "profile-sbx"


def test_sandbox_gate_blocks_real_side_effects():
    orchestrator = _mk_orchestrator(
        {
            "agent_runtime_v2_enabled": True,
            "agent_runtime_v2": {
                "sandbox": {
                    "allow_effect_actions": [],
                }
            },
        },
        side_effect="idempotent",
    )
    blocked = orchestrator._apply_runtime_v2_sandbox_gate(
        exec_context={
            "execution_context_envelope": {
                "environment_mode": "sandbox",
                "sandbox_profile_id": "profile-1",
            }
        },
        action_id="browser.control.run",
        action_args={"goal": "abrir"},
    )
    assert isinstance(blocked, dict)
    assert blocked.get("ok") is True
    assert ((blocked.get("data") or {}).get("simulated")) is True


def test_sandbox_gate_allows_read_only_actions():
    orchestrator = _mk_orchestrator(
        {
            "agent_runtime_v2_enabled": True,
            "agent_runtime_v2": {
                "sandbox": {
                    "allow_effect_actions": [],
                }
            },
        },
        side_effect="none",
    )
    allowed = orchestrator._apply_runtime_v2_sandbox_gate(
        exec_context={
            "execution_context_envelope": {
                "environment_mode": "sandbox",
                "sandbox_profile_id": "profile-1",
            }
        },
        action_id="browser.control.inspect",
        action_args={},
    )
    assert allowed is None


def test_runtime_v2_receipt_contains_sandbox_fields():
    receipt = AgentOrchestrator._build_runtime_v2_receipt(
        exec_context={
            "execution_context_envelope": {
                "environment_mode": "sandbox",
                "sandbox_profile_id": "profile-a",
                "tenant_id": "tenant-a",
                "qos_class": "LOW",
                "risk_level": "medium",
                "policy_version": "policy_v4",
            },
            "runtime_v2_governance": {
                "policy_decision": {
                    "decision": "allow_with_constraints",
                    "policy_mode": "log_only",
                    "explanation": {
                        "explanation_id": "x1",
                        "reason": "sandbox",
                    },
                }
            },
        },
        latency_ms=10,
    )
    assert receipt["environment_mode"] == "sandbox"
    assert receipt["sandbox_profile_id"] == "profile-a"
