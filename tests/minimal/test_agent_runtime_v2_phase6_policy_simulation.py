import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.services.agent_runtime_v2 import PolicySimulationMode
from src.core.orchestrator import AgentOrchestrator


def _base_envelope():
    return {
        "tenant_id": "tenant-a",
        "action_id": "browser.control.run",
        "risk_level": "high",
        "qos_class": "LOW",
        "metadata": {
            "domain": "web",
            "page_type": "checkout",
        },
    }


def test_single_policy_eval_returns_structured_decision():
    sim = PolicySimulationMode()
    out = sim.single_policy_eval(
        envelope_payload=_base_envelope(),
        action_params={"goal": "comprar"},
        policy_cfg={"mode": "log_only"},
    )
    assert out["mode"] == "single_policy_eval"
    assert isinstance(out.get("decision"), dict)
    assert str((out["decision"].get("decision") or "")).strip() != ""


def test_diff_eval_detects_decision_change():
    sim = PolicySimulationMode()
    out = sim.diff_eval(
        envelope_payload=_base_envelope(),
        action_params={"goal": "comprar"},
        policy_current={"mode": "enforce", "allow_with_constraints_risk_levels": ["high"]},
        policy_candidate={"mode": "enforce", "deny_actions": ["browser.control.run"]},
    )
    assert out["mode"] == "diff_eval"
    assert out["changed"] is True
    assert out["current"]["decision"] == "allow_with_constraints"
    assert out["candidate"]["decision"] == "deny"


def test_historical_replay_eval_aggregates_changed_dimensions():
    sim = PolicySimulationMode()
    events = [
        {
            "execution_context_envelope": {
                "tenant_id": "tenant-a",
                "action_id": "browser.control.run",
                "risk_level": "high",
                "qos_class": "LOW",
                "metadata": {"domain": "web", "page_type": "checkout"},
            },
            "action_params": {"goal": "a"},
        },
        {
            "execution_context_envelope": {
                "tenant_id": "tenant-b",
                "action_id": "browser.control.run",
                "risk_level": "medium",
                "qos_class": "NORMAL",
                "metadata": {"domain": "web", "page_type": "search"},
            },
            "action_params": {"goal": "b"},
        },
    ]
    out = sim.historical_replay_eval(
        events=events,
        policy_current={"mode": "enforce", "allow_with_constraints_risk_levels": ["high"]},
        policy_candidate={"mode": "enforce", "deny_actions": ["browser.control.run"]},
    )
    assert out["mode"] == "historical_replay_eval"
    assert out["total_events"] == 2
    assert out["changed_events"] >= 1
    agg = out.get("aggregates") or {}
    assert isinstance(agg.get("tenant"), dict)


def test_orchestrator_policy_simulation_helper_diff_eval():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._runtime_v2_policy_simulation = PolicySimulationMode()
    result = orchestrator._simulate_runtime_v2_policy(
        mode="diff_eval",
        envelope_payload=_base_envelope(),
        action_params={"goal": "comprar"},
        policy_current={"mode": "enforce", "allow_with_constraints_risk_levels": ["high"]},
        policy_candidate={"mode": "enforce", "deny_actions": ["browser.control.run"]},
    )
    assert result.get("mode") == "diff_eval"
    assert result.get("changed") is True
