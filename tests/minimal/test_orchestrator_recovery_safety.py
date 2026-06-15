import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.orchestrator import AgentOrchestrator
from core.resolution.action_plan import ActionPlan
from drivers.llm.base import ProviderContractError


class _FakeIntent:
    def __init__(self):
        self.action = "reply"
        self.params = {}
        self.response_text = ""
        self.thought = "relevant thought"
        self.attachments = None
        self.plan = None
        self.state_summary = None
        self.task_label = None
        self.model_used = "stub"


class _FakeLLMManager:
    def get_active_config(self):
        return {"max_context": 8000}

    def generate_intent(self, user_input, history, system_prompt, attachments=None):
        return _FakeIntent()

    def generate_text(self, prompt, system_prompt, max_tokens=256, temperature=0.7):
        raise ProviderContractError(
            "LLMManager generate_text returned empty output.",
            details={
                "error_stage": "llm_manager",
                "error_type": "manager_empty_output",
                "error_reason": "generate_text_returned_empty",
                "provider_used": "openai",
                "provider_parse_status": "empty_output",
                "provider_fallback_reason": "provider_empty_output",
                "provider_schema_mode": "text",
                "provider_contract_mode": "text",
                "raw_preview": "",
                "raw_preview_truncated": False,
                "raw_preview_chars": 0,
                "semantic_authority": False,
                "diagnostic_source": "llm_manager",
            },
        )


class _FakeSession:
    def __init__(self):
        self.context = {"user_language": "pt-BR"}
        self.state_summary = {}

    def get_context_for_llm(self, **kwargs):
        return []


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


def test_sanitize_user_facing_response_turns_empty_into_honest_failure():
    audit = {}
    reply = AgentOrchestrator._sanitize_user_facing_response(
        "",
        language="pt-BR",
        audit=audit,
    )

    assert reply
    assert "falh" in reply.lower() or "tentei responder" in reply.lower()
    assert audit["reason_code"] == "empty_response"
    assert audit["sanitized_text"] == reply


def test_status_label_is_short_and_does_not_reuse_fallback_text():
    label = AgentOrchestrator._build_status_label("no_plan", language="pt-BR")
    fallback = AgentOrchestrator._build_honest_fallback_reply(
        language="pt-BR",
        reason_code="recovery_empty",
    )

    assert label
    assert "LLMManager" not in label
    assert label != fallback
    assert "falh" not in label.lower()


def test_generate_recovery_reply_records_diagnostic_when_text_recovery_fails():
    orchestrator = object.__new__(AgentOrchestrator)
    orchestrator.llm_manager = _FakeLLMManager()
    orchestrator.i18n = SimpleNamespace(t=lambda key, locale=None, **kwargs: key)
    orchestrator._session_locale = lambda session, fallback="en": "pt-BR"
    session = _FakeSession()

    reply = orchestrator._generate_recovery_reply(
        session=session,
        user_input="onde fica o volume",
        reason="intent_none",
    )

    assert reply
    assert "falh" in reply.lower() or "tentei responder" in reply.lower()
    assert session.context["last_recovery_failure"]["error_stage"] == "recovery"
    assert session.context["last_recovery_failure"]["provider_used"] == "openai"
    assert session.state_summary["last_recovery_failure"]["error_type"] == "recovery_error"


def test_persist_confidence_diagnostics_stores_provider_diagnostics():
    orchestrator = object.__new__(AgentOrchestrator)
    captured = {}
    orchestrator._touch_work_context = lambda work_id, patch: captured.update(patch)
    session = _FakeSession()
    plan = ActionPlan(
        action_id="error",
        metadata={
            "confidence_diagnostics": {
                "score": 0.0,
                "threshold": 0.65,
                "reason_codes": ["provider_parse"],
                "reason_types": ["provider_error"],
                "semantic_authority": False,
                "action_is_reply": True,
                "action": "reply",
                "model_used": "hf-test",
            },
            "state_summary": {
                "provider_used": "huggingface",
                "provider_fallback_reason": "provider_parse_error",
                "provider_parse_status": "invalid_json",
                "error_stage": "provider",
                "error_type": "provider_exception",
                "error_reason": "invalid_json",
                "diagnostic_source": "huggingface",
                "raw_preview": "{\"action\": \"reply\"}",
                "raw_preview_truncated": False,
                "raw_preview_chars": 19,
                "semantic_authority": False,
            },
            "error_code": "low_confidence",
        },
    )

    rejection = orchestrator._persist_confidence_diagnostics(
        session,
        "work-1",
        plan,
        stage="initial_resolution",
        error_code="low_confidence",
    )

    assert rejection is not None
    assert session.context["last_provider_diagnostics"]["provider_used"] == "huggingface"
    assert session.state_summary["last_provider_diagnostics"]["provider_parse_status"] == "invalid_json"
    assert captured["data"]["last_provider_diagnostics"]["provider_fallback_reason"] == "provider_parse_error"
    assert session.state_summary["last_provider_diagnostics"]["raw_preview"] == "{\"action\": \"reply\"}"
