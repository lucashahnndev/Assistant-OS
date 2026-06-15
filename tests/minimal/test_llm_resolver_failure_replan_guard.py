import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.resolution.llm_resolver import LLMResolver


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


class _FakeSession:
    def __init__(self):
        self.context = {"user_language": "pt-BR"}

    def get_context_for_llm(self, **kwargs):
        return []


def test_reply_without_text_recovery_allowed_without_recent_failure():
    resolver = LLMResolver(_FakeLLMManager(), threshold=0.65)
    plan = resolver.resolve(
        "onde fica o volume",
        {"session": _FakeSession(), "history": [], "system_prompt": "x"},
    )
    assert plan is not None
    assert plan.action_id == "error"
    diagnostics = plan.metadata.get("confidence_diagnostics")
    assert diagnostics["semantic_authority"] is False
    assert "reply_with_thought_only" in diagnostics["reason_codes"]
    assert "thought_present" in diagnostics["reason_codes"]
    assert "format" in diagnostics["reason_types"]


def test_reply_without_text_recovery_blocked_after_recent_failure():
    resolver = LLMResolver(_FakeLLMManager(), threshold=0.65)
    plan = resolver.resolve(
        "onde fica o volume",
        {
            "session": _FakeSession(),
            "history": [],
            "system_prompt": "x",
            "last_action_status": "failure",
            "last_action_id": "vision.locate_screen",
            "last_action_reason": "ELEMENT_NOT_FOUND",
        },
    )
    assert plan is not None
    assert plan.action_id == "error"
    diagnostics = plan.metadata.get("confidence_diagnostics")
    assert diagnostics["semantic_authority"] is False
    assert diagnostics["score"] < 0.65
