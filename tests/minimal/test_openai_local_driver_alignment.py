import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.intent import AgentIntent
from src.drivers.providers.openai import llm as openai_llm
from src.drivers.providers.openai.llm import OpenAIChatProvider


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
                    "thought": "Pergunta de conversa simples.",
                    "action": "demo.openai",
                    "params": {"text": "hello"},
                    "response_text": "hello",
                    "plan": [],
                    "state_summary": {},
                    "task_label": "saudacao",
                },
                ensure_ascii=False,
            )
        )


def test_openai_local_provider_preserves_action_and_response_text(monkeypatch):
    monkeypatch.setattr(openai_llm, "OpenAI", _FakeOpenAIClient)

    provider = OpenAIChatProvider(
        {
            "base_url": "http://127.0.0.1:8081/v1",
            "model": "qwen2.5-7b-instruct-q5",
            "structured_mode": "auto",
            "intent_repair_attempts": 0,
        }
    )

    intent = provider.generate_intent(
        "qual o seu nome?",
        history=[],
        system_prompt="Responder conversas simples em JSON.",
    )

    assert isinstance(intent, AgentIntent)
    assert intent.action == "demo.openai"
    assert intent.thought == "Pergunta de conversa simples."
    assert intent.response_text == "hello"
    assert provider.client.chat.completions.calls, "expected the fake client to be called"
    assert provider.client.chat.completions.calls[0]["response_format"]["type"] == "json_schema"


def test_openai_local_provider_canonicalizes_weather_alias(monkeypatch):
    monkeypatch.setattr(openai_llm, "OpenAI", _FakeOpenAIClient)

    provider = OpenAIChatProvider(
        {
            "base_url": "http://127.0.0.1:8081/v1",
            "model": "qwen2.5-7b-instruct-q5",
            "structured_mode": "auto",
            "intent_repair_attempts": 0,
        }
    )
    provider.client.chat.completions.response_payload = json.dumps(
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

    intent = provider.generate_intent(
        "como está o clima?",
        history=[],
        system_prompt="Responder em JSON.",
        allowed_actions=["weather.control.get", "weather.control.forecast"],
        capability_registry=None,
    )

    assert intent.action == "weather.fetch_current_conditions"
