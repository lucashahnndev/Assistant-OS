from types import SimpleNamespace

from drivers.llm.openrouter_driver import OpenRouterProvider
from services.llm.prompt_composer import PromptComposer


def _base_prompt_kwargs():
    return {
        "agent_name": "Atlas",
        "personality": "Technical and concise.",
        "specialist_prompt": "",
        "presentation_directive": "[PRESENTATION DIRECTIVE]\n- Use markdown when useful.",
        "sys_info": {"date": "2026-02-22", "time": "10:00:00", "os": "Linux", "user": "lucas"},
        "location": "Canoas",
        "channel": "web",
        "user_name": "tester",
        "user_language": "pt-BR",
        "toon_state": "{\"goal\": \"standby\"}",
        "user_input": "me diga a previsão do tempo",
        "project_path": "/tmp/project",
        "workspace_path": "/tmp/workspace",
        "venv_python": "/tmp/project/env/bin/python3",
        "venv_pip": "/tmp/project/env/bin/pip",
        "browser_pages": [],
        "session_summary": "",
        "scratchpad": "",
        "attachments": [],
        "skills_summary": "- `weather.control.now`: current weather",
        "skill_scope": "principal-filtered",
    }


def test_prompt_composer_omits_irrelevant_dynamic_sections():
    composer = PromptComposer()
    prompt = composer.compose(**_base_prompt_kwargs())

    assert "[BROWSER STATE]" not in prompt
    assert "[PYTHON CONTEXT]" not in prompt
    assert "[SESSION ATTACHMENTS]" not in prompt
    assert "[STRUCTURED OUTPUT CONTRACT]" in prompt
    assert "Scope: principal-filtered" in prompt
    assert "Detected user language: pt-BR" in prompt


def test_prompt_composer_includes_browser_and_dev_context_when_needed():
    composer = PromptComposer()
    kwargs = _base_prompt_kwargs()
    kwargs["user_input"] = "abra o browser e depois crie um script python"
    kwargs["browser_pages"] = [{"title": "YouTube", "url": "https://youtube.com"}]

    prompt = composer.compose(**kwargs)

    assert "[BROWSER STATE]" in prompt
    assert "[PYTHON CONTEXT]" in prompt
    assert "youtube.com" in prompt


def test_prompt_composer_clips_large_blocks_by_budget():
    composer = PromptComposer()
    kwargs = _base_prompt_kwargs()
    kwargs["user_input"] = "abra o browser e analise"
    kwargs["browser_pages"] = [{"title": "X" * 2000, "url": "https://example.com"}]
    kwargs["scratchpad"] = "N" * 3000
    kwargs["skills_summary"] = "S" * 12000

    prompt = composer.compose(**kwargs)

    assert "...[truncated:scratchpad]" in prompt
    assert "...[truncated:skills_summary]" in prompt


class _DummyCompletions:
    def __init__(self):
        self.last_messages = None

    def create(self, **kwargs):
        self.last_messages = kwargs["messages"]
        payload = '{"thought":"ok","action":"reply","params":{},"response_text":"done"}'
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
        )


class _DummyClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_DummyCompletions())


def test_openrouter_driver_uses_core_prompt_without_internal_augmentation():
    provider = OpenRouterProvider({"api_key": "test-key", "model": "dummy/model"})
    dummy_client = _DummyClient()
    provider.client = dummy_client

    intent = provider.generate_intent(
        user_input="oi",
        history=[{"role": "assistant", "content": "hello"}],
        system_prompt="SYSTEM_PROMPT_FROM_CORE",
    )

    sent_messages = dummy_client.chat.completions.last_messages
    assert sent_messages[0]["content"] == "SYSTEM_PROMPT_FROM_CORE"
    assert "ARCHITECTURAL RULES" not in sent_messages[0]["content"]
    assert intent.action == "reply"
