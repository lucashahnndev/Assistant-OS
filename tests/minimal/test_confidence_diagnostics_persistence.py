import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.core.orchestrator import AgentOrchestrator
from src.core.resolution.action_plan import ActionPlan
from src.core.session import Session


class _TouchCapture:
    def __init__(self):
        self.calls = []

    def __call__(self, work_id, patch):
        self.calls.append((work_id, patch))


def test_confidence_diagnostics_are_persisted_for_rejected_plans():
    orch = object.__new__(AgentOrchestrator)
    touch_capture = _TouchCapture()
    orch._touch_work_context = touch_capture

    session = Session("session-confidence", source="web")
    session.context = {}
    session.state_summary = {"cursor": "1/1 (step: init)"}

    plan = ActionPlan(
        action_id="error",
        source="llm_low_confidence",
        model_used="stub-model",
        metadata={
            "error_code": "low_confidence",
            "attempted_action": "reply",
            "confidence_diagnostics": {
                "score": 0.21,
                "threshold": 0.65,
                "reason_codes": ["reply_with_thought_only"],
                "reason_types": ["format"],
                "semantic_authority": False,
                "action": "reply",
                "action_is_reply": True,
                "model_used": "stub-model",
            },
        },
    )

    rejection = AgentOrchestrator._persist_confidence_diagnostics(
        orch,
        session,
        "work-123",
        plan,
        stage="initial_resolution",
        error_code="low_confidence",
    )

    assert rejection is not None
    assert session.context["last_confidence_diagnostics"]["score"] == 0.21
    assert session.context["last_confidence_rejection"]["attempted_action"] == "reply"
    assert session.state_summary["last_confidence_score"] == 0.21
    assert session.state_summary["last_confidence_threshold"] == 0.65
    assert session.state_summary["last_confidence_action"] == "reply"
    assert session.state_summary["last_confidence_action_is_reply"] is True
    assert touch_capture.calls

    work_id, patch = touch_capture.calls[0]
    assert work_id == "work-123"
    assert patch["summary"]["last_confidence_score"] == 0.21
    assert patch["summary"]["last_confidence_threshold"] == 0.65
    assert patch["summary"]["last_confidence_model_used"] == "stub-model"
    assert patch["data"]["last_confidence_diagnostics"]["semantic_authority"] is False


def test_confidence_diagnostics_are_persisted_for_provider_error_plans():
    orch = object.__new__(AgentOrchestrator)
    touch_capture = _TouchCapture()
    orch._touch_work_context = touch_capture

    session = Session("session-confidence-provider", source="web")
    session.context = {}
    session.state_summary = {"cursor": "1/1 (step: init)"}

    plan = ActionPlan(
        action_id="error",
        source="llm_error",
        model_used=None,
        metadata={
            "error_code": "unknown_error",
            "confidence_diagnostics": {
                "score": 0.0,
                "threshold": 0.65,
                "reason_codes": ["provider_error"],
                "reason_types": ["provider_error"],
                "semantic_authority": False,
                "action": "error",
                "action_is_reply": False,
                "model_used": None,
            },
        },
    )

    rejection = AgentOrchestrator._persist_confidence_diagnostics(
        orch,
        session,
        "work-124",
        plan,
        stage="provider_error",
        error_code="unknown_error",
    )

    assert rejection is not None
    assert session.context["last_confidence_diagnostics"]["reason_codes"] == ["provider_error"]
    assert session.context["last_confidence_rejection"]["error_code"] == "unknown_error"
    assert touch_capture.calls

    _, patch = touch_capture.calls[0]
    assert patch["summary"]["last_confidence_reason_codes"] == ["provider_error"]
    assert patch["summary"]["last_confidence_action"] == "error"
