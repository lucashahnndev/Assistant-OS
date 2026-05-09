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
        self.thought = ""
        self.attachments = None
        self.plan = None
        self.state_summary = None
        self.task_label = None


class _FakeLLMManager:
    def get_active_config(self):
        return {"max_context": 8000}

    def generate_intent(self, user_input, history, system_prompt, attachments=None, **kwargs):
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


def test_greeting_turn_forces_reply_even_if_provider_returns_tool_action():
    class _GreetingIntent(_FakeIntent):
        def __init__(self):
            super().__init__()
            self.action = "system.control.capabilities.describe.ai"
            self.response_text = "Olá, posso ajudar."

    class _GreetingLLMManager(_FakeLLMManager):
        def generate_intent(self, user_input, history, system_prompt, attachments=None, **kwargs):
            return _GreetingIntent()

    resolver = LLMResolver(_GreetingLLMManager(), threshold=0.65)
    plan = resolver.resolve(
        "oi",
        {"session": _FakeSession(), "history": [], "system_prompt": "x"},
    )

    assert plan is not None
    assert plan.action_id == "reply"
    assert plan.response_text == "Olá, posso ajudar."


def test_discovery_scope_limits_allowed_actions_to_candidates_plus_reply():
    captured = {}

    class _ScopedLLMManager(_FakeLLMManager):
        def generate_intent(self, user_input, history, system_prompt, attachments=None, **kwargs):
            captured["allowed_actions"] = kwargs.get("allowed_actions")
            return _FakeIntent()

    class _DiscoverySession(_FakeSession):
        def __init__(self):
            super().__init__()
            self.state_summary = {
                "last_tool_discovery": {
                    "query": "clima",
                    "intent": "task_execution",
                    "domain": "weather",
                    "role": "search",
                    "entity_type": "weather_report",
                    "count": 2,
                },
                "tool_candidates": ["weather.control.get", "weather.control.forecast"],
            }

    resolver = LLMResolver(_ScopedLLMManager(), threshold=0.65)
    plan = resolver.resolve(
        "como está o clima?",
        {
            "session": _DiscoverySession(),
            "history": [],
            "system_prompt": "x",
            "allowed_actions": ["weather.control.get", "weather.control.forecast", "system.control.consult_tools", "memory_management.recall"],
        },
    )

    assert plan is not None
    assert captured["allowed_actions"][0] == "weather.control.get"
    assert "weather.control.get" in captured["allowed_actions"]
    assert "weather.control.forecast" in captured["allowed_actions"]
    assert "system.control.consult_tools" in captured["allowed_actions"]
    assert "reply" in captured["allowed_actions"]
    assert "memory_management.recall" not in captured["allowed_actions"]


def test_discovery_primary_overrides_out_of_scope_provider_action():
    class _PrimaryIntent(_FakeIntent):
        def __init__(self):
            super().__init__()
            self.action = "weather.get_current_conditions"
            self.response_text = "Verificando o clima."

    class _PrimaryLLMManager(_FakeLLMManager):
        def generate_intent(self, user_input, history, system_prompt, attachments=None, **kwargs):
            return _PrimaryIntent()

    class _DiscoverySession(_FakeSession):
        def __init__(self):
            super().__init__()
            self.state_summary = {
                "last_tool_discovery": {
                    "query": "clima",
                    "intent": "task_execution",
                    "domain": "weather",
                    "role": "search",
                    "entity_type": "weather_report",
                    "count": 2,
                    "primary_action_id": "weather.control.get",
                },
                "tool_candidates": ["weather.control.get", "weather.control.forecast"],
            }

    resolver = LLMResolver(_PrimaryLLMManager(), threshold=0.65)
    plan = resolver.resolve(
        "como está o clima?",
        {
            "session": _DiscoverySession(),
            "history": [],
            "system_prompt": "x",
            "allowed_actions": ["weather.control.get", "weather.control.forecast", "system.control.consult_tools"],
        },
    )

    assert plan is not None
    assert plan.action_id == "weather.control.get"
