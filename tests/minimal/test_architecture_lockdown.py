import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.action_gateway import ActionGateway
from core.errors import AgentSemanticError, SyntaxError as AgentSyntaxError
from core.intent import AgentIntent
from core.plan_validator import PlanValidator
from core.resolution.action_plan import ActionPlan
from core.output_governor import OutputGovernor
from services.llm.prompt_composer import PromptComposer
from src.drivers.providers.gemini import llm as gemini_llm
from src.drivers.providers.huggingface import llm as hf_llm
from src.drivers.providers.ollama import llm as ollama_llm
from src.drivers.providers.openai import llm as openai_llm
from src.drivers.providers.openai.parser import extract_and_parse_json as openai_parse
from src.drivers.providers.openrouter import llm as openrouter_llm
from src.drivers.providers.openrouter.parser import extract_and_parse_json as openrouter_parse


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(SimpleNamespace(content=content, tool_calls=None))]


class _FakeOpenAIClient:
    def __init__(self, response_payload: str):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                calls=[],
                create=self._create,
            )
        )
        self._response_payload = response_payload

    def _create(self, **kwargs):
        self.chat.completions.calls.append(kwargs)
        return _FakeResponse(self._response_payload)


class _FakeRequestsResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class _FakeGeminiClient:
    def __init__(self, response_text: str):
        self.models = SimpleNamespace(generate_content=self._generate_content)
        self._response_text = response_text

    def _generate_content(self, **kwargs):
        return SimpleNamespace(text=self._response_text)


def _intent_payload(action: str = "demo.action") -> str:
    return json.dumps(
        {
            "thought": "test thought",
            "action": action,
            "params": {"text": "hello"},
            "response_text": "hello",
            "plan": [],
            "state_summary": {},
            "task_label": "label",
            "attachments": [],
        },
        ensure_ascii=False,
    )


def test_legacy_repair_paths_are_not_imported_in_provider_llm_files():
    provider_files = [
        ROOT / "src/drivers/providers/openai/llm.py",
        ROOT / "src/drivers/providers/openrouter/llm.py",
        ROOT / "src/drivers/providers/gemini/llm.py",
        ROOT / "src/drivers/providers/huggingface/llm.py",
        ROOT / "src/drivers/providers/ollama/llm.py",
    ]
    banned_tokens = [
        "build_repair_prompt",
        "normalize_action_id",
        "validate_intent_payload",
        "describe_repair_issue",
        "extract_action_catalog",
        "intent_repair",
    ]
    for path in provider_files:
        text = path.read_text(encoding="utf-8")
        for token in banned_tokens:
            assert token not in text, f"{token} leaked into {path}"


def test_orchestrator_uses_gateway_not_direct_registry_dispatch():
    text = (ROOT / "src/core/orchestrator.py").read_text(encoding="utf-8")
    assert "self.action_gateway.execute_action(" in text
    assert "capability_registry.dispatch(" not in text


def test_prompt_composer_strict_mode_is_context_only(monkeypatch):
    composer = PromptComposer()
    prompt = composer.compose(
        agent_name="Kernel",
        personality="calm",
        response_persona="reply plainly",
        specialist_prompt="specialist",
        presentation_directive="present",
        instruction_pack="",
        sys_info={"date": "2026-03-31", "time": "10:00", "timezone": "America/Sao_Paulo", "os": "Linux"},
        location="BR",
        channel="chat",
        user_name="user",
        user_language="en",
        toon_state="state",
        toon_deltas=[],
        user_input="hello",
        project_path="/tmp",
        workspace_path="/tmp",
        venv_python="/usr/bin/python3",
        venv_pip="/usr/bin/pip",
        browser_pages=[],
        session_summary="summary",
        scratchpad="scratch",
        attachments=[],
        capabilities_summary="caps",
        capability_scope="scope",
        relevant_memory=[],
    )
    assert "[SYSTEM CONTEXT]" in prompt
    assert "[USER INPUT]" in prompt
    assert "[TOON STATE]" in prompt
    assert "consult_tools" not in prompt
    assert "fallback" not in prompt.lower()
    assert "[ASSISTIVE MODE DIRECTIVE]" not in prompt
    assert "[RESPONSE PERSONA]" not in prompt
    assert "[INSTRUCTION PACK]" not in prompt


@pytest.mark.parametrize(
    "parser",
    [openai_parse, openrouter_parse],
)
def test_parser_strict_mode_rejects_invalid_json(parser):
    with pytest.raises(AgentSyntaxError):
        parser("not json", strict=True)


def test_action_gateway_rejects_unknown_action_without_correction():
    gateway = ActionGateway()
    dispatch_calls = []

    class _Registry:
        def get_capability_for_action(self, action_id):
            return None

        def get_action_metadata(self, action_id):
            return {}

        def dispatch(self, action_id, params, context):
            dispatch_calls.append((action_id, params, context))
            return {"ok": True}

        def list_actions(self):
            return ["allowed.action"]

    decision = gateway.resolve(
        action_id="bad.action",
        params={},
        allowed_actions=["allowed.action"],
        capability_registry=_Registry(),
        capability_metadata={},
        strict_mode=False,
    )
    assert decision.outcome == "REJECT"
    assert dispatch_calls == []

    with pytest.raises(AgentSemanticError):
        gateway.resolve(
            action_id="bad.action",
            params={},
            allowed_actions=["allowed.action"],
            capability_registry=_Registry(),
            capability_metadata={},
            strict_mode=True,
        )


def test_plan_validator_does_not_mutate_input():
    class _CapRegistry:
        def get_capability_for_action(self, action_id):
            return object() if action_id == "browser.control.run" else None

        def get_action_metadata(self, action_id):
            return {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "intent_class": {
                            "type": "string",
                            "enum": ["realizar_pesquisa"],
                        }
                    },
                    "required": ["intent_class"],
                    "additionalProperties": True,
                }
            } if action_id == "browser.control.run" else {}

    class _Session:
        tool_health = {}
        drivers_state = {}

    plan = ActionPlan(action_id="browser.control.run", args={"goal": "abrir"}, confidence=0.9, source="llm")
    result = PlanValidator.validate(plan=plan, capability_registry=_CapRegistry(), session=_Session(), context={})
    assert result.is_valid is False
    assert plan.args == {"goal": "abrir"}


@pytest.mark.parametrize(
    "provider_cls, module, factory_attr, response_payload, expected_action",
    [
        (
            openai_llm.OpenAIChatProvider,
            openai_llm,
            "OpenAI",
            _intent_payload("demo.openai"),
            "demo.openai",
        ),
        (
            openrouter_llm.OpenRouterProvider,
            openrouter_llm,
            "OpenAI",
            _intent_payload("demo.openrouter"),
            "demo.openrouter",
        ),
        (
            hf_llm.HuggingFaceProvider,
            hf_llm,
            "requests",
            _intent_payload("demo.hf"),
            "demo.hf",
        ),
        (
            ollama_llm.OllamaProvider,
            ollama_llm,
            "requests",
            _intent_payload("demo.ollama"),
            "demo.ollama",
        ),
        (
            gemini_llm.GeminiProvider,
            gemini_llm,
            "genai",
            _intent_payload("demo.gemini"),
            "demo.gemini",
        ),
    ],
)
def test_providers_preserve_action_id_without_fallback(monkeypatch, provider_cls, module, factory_attr, response_payload, expected_action):
    if factory_attr == "OpenAI":
        monkeypatch.setattr(module, "OpenAI", lambda **kwargs: _FakeOpenAIClient(response_payload))
    elif factory_attr == "requests":
        monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: _FakeRequestsResponse(response_payload))
    elif factory_attr == "genai":
        monkeypatch.setattr(module, "genai", SimpleNamespace(Client=lambda **kwargs: _FakeGeminiClient(response_payload)))
        monkeypatch.setattr(
            module,
            "types",
            SimpleNamespace(GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs)),
        )

    if provider_cls.__name__ == "OpenAIChatProvider":
        provider = provider_cls({"base_url": "http://localhost:1", "model": "gpt-4o-mini", "secret_ref": ""})
        intent = provider.generate_intent("hello", [], "system")
    elif provider_cls.__name__ == "OpenRouterProvider":
        provider = provider_cls({"secret_ref": "", "model": "openai/gpt-4o-mini"})
        intent = provider.generate_intent("hello", [], "system")
    elif provider_cls.__name__ == "HuggingFaceProvider":
        provider = provider_cls({"api_key": "", "model": "test"})
        intent = provider.generate_intent("hello", [], "system")
    elif provider_cls.__name__ == "OllamaProvider":
        provider = provider_cls({"url": "http://localhost:11434/api/chat", "model": "llama3"})
        intent = provider.generate_intent("hello", [], "system")
    else:
        provider = provider_cls({"secret_ref": "", "model": "gemini-2.0-flash"})
        intent = provider.generate_intent("hello", [], "system")

    assert isinstance(intent, AgentIntent)
    assert intent.action == expected_action
    assert intent.response_text == "hello"
    assert intent.params == {"text": "hello"}


def test_output_governor_rejects_thought_leak():
    result = OutputGovernor.classify_final_user_response(
        user_input="oi",
        response_text="The user seems to want a greeting. I will answer now.",
        session_language="pt-BR",
    )

    assert result.accepted is False
    assert result.rejection_reason == "thought_leak"
    assert "analysis" in result.retry_instruction.lower() or "final answer" in result.retry_instruction.lower()


def test_output_governor_rejects_language_mismatch():
    result = OutputGovernor.classify_final_user_response(
        user_input="oi",
        response_text="Hello, how can I help?",
        session_language="pt-BR",
    )

    assert result.accepted is False
    assert result.rejection_reason == "language_mismatch"
    assert "same language" in result.retry_instruction.lower()
