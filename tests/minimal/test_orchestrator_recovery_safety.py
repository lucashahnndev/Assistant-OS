import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.orchestrator import AgentOrchestrator


def test_summarize_last_success_data_accepts_keyword_only_call():
    out = AgentOrchestrator._summarize_last_success_data(
        action_id="weather.control.get",
        structured_result={"location": "Porto Alegre", "current": {"temp_c": 22}},
        raw_output="{}",
    )

    assert out["action_id"] == "weather.control.get"
    assert out["status"] == "success"
    assert out["location"] == "Porto Alegre"
    assert out["current"] == {"temp_c": 22}


def test_summarize_last_success_data_handles_vision_payload():
    out = AgentOrchestrator._summarize_last_success_data(
        action_id="vision.locate_screen",
        structured_result={"text": "botao enviar"},
        raw_output='{"text":"botao enviar"}',
    )

    assert out["action_id"] == "vision.locate_screen"
    assert out["observation"] == "botao enviar"


def test_assess_action_result_treats_partial_as_partial():
    status, reason = AgentOrchestrator._assess_action_result(
        {"ok": True, "status": "partial", "result": {"status": "partial"}},
        raw_result='{"ok":true,"status":"partial"}',
    )

    assert status == "partial"
    assert reason == "partial"


def test_assess_action_result_treats_completed_as_success():
    status, reason = AgentOrchestrator._assess_action_result(
        {"ok": True, "status": "completed"},
        raw_result='{"ok":true,"status":"completed"}',
    )

    assert status == "success"
    assert reason == "completed"


def test_ground_reply_against_partial_is_neutral():
    reply = AgentOrchestrator._ground_reply_against_last_result(
        response_text="Concluí tudo com sucesso.",
        last_action_status="partial",
        last_action_id="obsidian.note.create",
        last_action_reason="fallback",
        last_action_output='{"status":"partial"}',
        language="pt-BR",
    )

    assert "SUCCESS_HALLUCINATION_DETECTED" in reply
