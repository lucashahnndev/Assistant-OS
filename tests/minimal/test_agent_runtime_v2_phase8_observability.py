import sys
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.core.orchestrator import AgentOrchestrator
from src.services.agent_runtime_v2 import RuntimeV2Observability


class _Cfg:
    def __init__(self, base_data_dir: str, runtime_cfg=None):
        self.base_data_dir = base_data_dir
        self._runtime_cfg = runtime_cfg if isinstance(runtime_cfg, dict) else None

    def get(self, key, default=None):
        if key == "runtime" and self._runtime_cfg is not None:
            return self._runtime_cfg
        return default


def test_runtime_v2_observability_records_snapshot_and_event_file():
    with tempfile.TemporaryDirectory() as tmp:
        obs = RuntimeV2Observability(config_manager=_Cfg(tmp))
        snapshot = obs.record_execution_event(
            {
                "session_id": "s1",
                "work_id": "w1",
                "action_id": "browser.control.run",
                "result_status": "failure",
                "result_reason": "POLICY_DENIED",
                "latency_ms": 33,
                "tenant_id": "tenant-a",
                "qos_class": "HIGH",
                "risk_level": "high",
                "policy_version": "policy_v2",
                "policy_decision": "deny",
                "environment_mode": "production",
            }
        )

        assert snapshot["events_total"] == 1
        assert snapshot["failure_total"] == 1
        assert snapshot["deny_total"] == 1
        assert snapshot["failure_rate"] == 1.0

        log_path = Path(tmp) / "runtime_v2" / "governance_events.jsonl"
        assert log_path.exists() is True
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert "browser.control.run" in lines[0]


def test_runtime_v2_observability_disabled_mode_no_event_written():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _Cfg(
            tmp,
            runtime_cfg={
                "agent_runtime_v2": {
                    "observability": {
                        "enabled": False,
                        "event_log": "runtime_v2/governance_events.jsonl",
                    }
                }
            },
        )
        obs = RuntimeV2Observability(config_manager=cfg)
        snapshot = obs.record_execution_event(
            {
                "session_id": "s1",
                "work_id": "w1",
                "action_id": "browser.control.run",
                "result_status": "success",
            }
        )
        assert snapshot["enabled"] is False
        assert snapshot["events_total"] == 0
        log_path = Path(tmp) / "runtime_v2" / "governance_events.jsonl"
        if log_path.exists():
            assert log_path.read_text(encoding="utf-8").strip() == ""


def test_runtime_v2_observability_builds_structured_replay_payload():
    with tempfile.TemporaryDirectory() as tmp:
        obs = RuntimeV2Observability(config_manager=_Cfg(tmp))
        payload = obs.build_replay_payload(
            envelope={
                "tenant_id": "tenant-a",
                "qos_class": "NORMAL",
                "risk_level": "medium",
                "policy_version": "policy_v3",
            },
            governance={
                "policy_decision": {
                    "decision": "allow_with_constraints",
                    "policy_mode": "enforce",
                    "explanation": {
                        "explanation_id": "business:constraint",
                        "reason": "low priority constrained",
                    },
                }
            },
            action_id="browser.control.run",
            action_args={"goal": "buscar"},
            result_status="success",
            result_reason="ok",
            latency_ms=71,
            loop_index=2,
        )

        assert payload["action_id"] == "browser.control.run"
        assert payload["loop"] == 2
        assert payload["policy_decision"]["decision"] == "allow_with_constraints"
        assert payload["policy_decision"]["explanation_id"] == "business:constraint"


def test_orchestrator_runtime_v2_observability_helper_records_and_touches_work_context():
    with tempfile.TemporaryDirectory() as tmp:
        orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
        orchestrator._runtime_v2_observability = RuntimeV2Observability(config_manager=_Cfg(tmp))

        touched = {}

        def _fake_touch(work_id, patch):
            touched["work_id"] = work_id
            touched["patch"] = patch

        orchestrator._touch_work_context = _fake_touch

        orchestrator._record_runtime_v2_observability(
            exec_context={
                "session_id": "session-1",
                "execution_context_envelope": {
                    "tenant_id": "tenant-a",
                    "qos_class": "HIGH",
                    "risk_level": "low",
                    "policy_version": "policy_v1",
                    "environment_mode": "sandbox",
                },
                "runtime_v2_governance": {
                    "policy_decision": {
                        "decision": "allow",
                        "policy_mode": "enforce",
                        "explanation": {
                            "explanation_id": "security:allow",
                            "reason": "allowed by policy",
                        },
                    }
                },
            },
            action_id="browser.control.run",
            action_args={"goal": "x"},
            result_status="success",
            result_reason="ok",
            latency_ms=10,
            loop_index=1,
            work_id="work-1",
        )

        assert touched["work_id"] == "work-1"
        runtime_v2_patch = touched["patch"]["runtime_v2"]
        assert isinstance(runtime_v2_patch.get("last_replay_payload"), dict)
        assert isinstance(runtime_v2_patch.get("metrics_snapshot"), dict)
        assert runtime_v2_patch["metrics_snapshot"]["events_total"] >= 1


def test_orchestrator_runtime_v2_observability_helper_skips_when_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _Cfg(
            tmp,
            runtime_cfg={
                "agent_runtime_v2": {
                    "observability": {
                        "enabled": False,
                    }
                }
            },
        )
        orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
        orchestrator._runtime_v2_observability = RuntimeV2Observability(config_manager=cfg)

        touched = {}

        def _fake_touch(work_id, patch):
            touched["work_id"] = work_id
            touched["patch"] = patch

        orchestrator._touch_work_context = _fake_touch

        orchestrator._record_runtime_v2_observability(
            exec_context={
                "session_id": "session-1",
                "execution_context_envelope": {
                    "tenant_id": "tenant-a",
                    "environment_mode": "production",
                },
                "runtime_v2_governance": {
                    "policy_decision": {
                        "decision": "allow",
                    }
                },
            },
            action_id="browser.control.run",
            action_args={},
            result_status="success",
            result_reason="ok",
            latency_ms=10,
            loop_index=1,
            work_id="work-1",
        )
        assert touched == {}
