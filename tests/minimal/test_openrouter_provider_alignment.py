import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.drivers.providers.openrouter import llm as openrouter_llm
from src.drivers.providers.openrouter.llm import OpenRouterProvider


class _FakeMessage:
    def __init__(self, content: str = "", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


class _FakeCompletions:
    def __init__(self, response_payload):
        self.response_payload = response_payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(_FakeMessage(content=self.response_payload))


class _FakeChat:
    def __init__(self, response_payload):
        self.completions = _FakeCompletions(response_payload)


class _FakeOpenAIClient:
    def __init__(self, *args, **kwargs):
        self.chat = _FakeChat(
            json.dumps(
                {
                    "thought": "O usuário quer o clima atual.",
                    "action": "weather.fetch_current_conditions",
                    "params": {"location": "Canoas, RS, Brazil"},
                    "response_text": "Aguarde, vou verificar o clima.",
                    "plan": [],
                    "state_summary": {},
                    "task_label": "weather lookup",
                },
                ensure_ascii=False,
            )
        )


def test_openrouter_provider_canonicalizes_weather_alias(monkeypatch):
    monkeypatch.setattr(openrouter_llm, "OpenAI", _FakeOpenAIClient)

    provider = OpenRouterProvider(
        {
            "secret_ref": "unused",
            "model": "arcee-ai/trinity-large-preview:free",
            "intent_repair_attempts": 0,
        }
    )

    intent = provider.generate_intent(
        "como está o clima?",
        history=[],
        system_prompt="Responder em JSON.",
        allowed_actions=["weather.control.get", "weather.control.forecast"],
        capability_registry=None,
    )

    assert intent.action == "weather.fetch_current_conditions"
    assert intent.response_text == "Aguarde, vou verificar o clima."
