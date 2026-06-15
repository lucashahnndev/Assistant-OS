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

from core.intent import AgentIntent
from drivers.llm.base import ProviderContractError, ILLMProvider
from services.llm.manager import LLMManager


class _FailingStructuredProvider:
    def __init__(self, model: str, message: str):
        self.model = model
        self._message = message

    def generate_structured(self, *args, **kwargs):
        raise ValueError(self._message)


class _WorkingStructuredProvider:
    def __init__(self, model: str, payload: dict):
        self.model = model
        self._payload = payload

    def generate_structured(self, *args, **kwargs):
        return dict(self._payload)


class _FailingIntentProvider:
    def __init__(self, model: str, message: str):
        self.model = model
        self._message = message

    def generate_intent(self, *args, **kwargs):
        raise ValueError(self._message)


class _DiagnosticFailingIntentProvider:
    def __init__(self, model: str):
        self.model = model

    def generate_intent(self, *args, **kwargs):
        raise ILLMProvider.contract_error(
            "OpenRouter reply missing response_text.",
            provider_used="openrouter",
            error_stage="provider",
            error_type="provider_contract_error",
            error_reason="missing_response_text",
            raw_response={"action": "reply", "response_text": ""},
            provider_parse_status="missing_response_text",
            provider_fallback_reason="provider_contract_error",
            provider_schema_mode="intent_json",
            provider_contract_mode="intent",
            extra={"diagnostic_source": "openrouter"},
        )


class _WorkingIntentProvider:
    def __init__(self, model: str):
        self.model = model

    def generate_intent(self, user_input, history, system_prompt, attachments=None, **kwargs):
        return AgentIntent(
            thought="ok",
            action="reply",
            params={},
            response_text="done",
            state_summary={"semantic_authority": False},
            model_used=self.model,
        )


class _WhitespaceTextProvider:
    def __init__(self, model: str):
        self.model = model

    def generate_text(self, *args, **kwargs):
        return "   "


def _make_manager(*providers):
    manager = object.__new__(LLMManager)
    manager._last_router_meta = {}
    manager.provider_health = {str(idx): {"status": "online", "last_error": None, "priority": idx} for idx in range(1, len(providers) + 1)}
    manager.chat_pool = [
        {"id": str(idx), "provider": f"provider_{idx}", "instance": provider, "max_tokens": 4096, "max_context": 8000}
        for idx, provider in enumerate(providers, start=1)
    ]
    manager.vision_pool = []
    return manager


def test_structured_router_records_fallback_attempts_and_reason_codes():
    manager = _make_manager(
        _FailingStructuredProvider("model-a", "Invalid JSON payload"),
        _WorkingStructuredProvider("model-b", {"ok": True, "status": "success", "value": 7}),
    )

    result = manager.generate_structured_text("prompt", system_prompt="system", contract="demo")

    assert result["ok"] is True
    meta = manager.get_last_router_meta()
    assert meta["semantic_authority"] is False
    assert meta["provider_used"] == "provider_2"
    assert meta["provider_attempts_total"] == 2
    assert meta["provider_fallback_reason"] is None
    assert meta["provider_parse_status"] == "ok"
    assert meta["provider_schema_mode"] == "structured_json"
    assert meta["provider_contract_mode"] == "structured"
    assert meta["provider_attempts"][0]["reason_code"] == "provider_parse_error"
    assert meta["provider_attempts"][0]["status"] == "failed"
    assert meta["provider_attempts"][1]["status"] == "success"


def test_intent_router_persists_diagnostics_on_total_failure():
    manager = _make_manager(
        _FailingIntentProvider("model-a", "Timed out"),
        _FailingIntentProvider("model-b", "Timed out"),
    )

    intent = manager.generate_intent("hello", [], "system", strict_mode=True, paranoid_mode=True, intent_repair_attempts=2, allowed_actions=["reply"])

    assert intent.action == "error"
    assert intent.state_summary["semantic_authority"] is False
    assert intent.state_summary["provider_fallback_reason"] == "timeout"
    assert intent.state_summary["provider_parse_status"] == "timeout"
    assert intent.state_summary["provider_attempts_total"] == 2
    assert intent.state_summary["provider_schema_mode"] == "intent_json"
    assert intent.state_summary["strict_mode"] is True
    assert intent.state_summary["paranoid_mode"] is True
    assert intent.state_summary["intent_repair_attempts"] == 2
    assert intent.state_summary["allowed_actions_count"] == 1
    meta = manager.get_last_router_meta()
    assert meta["provider_fallback_reason"] == "timeout"
    assert meta["provider_parse_status"] == "timeout"
    assert meta["semantic_authority"] is False
    assert meta["provider_attempts"][0]["reason_code"] == "timeout"
    assert meta["provider_attempts"][1]["reason_code"] == "timeout"


def test_intent_router_propagates_raw_preview_and_parse_status():
    manager = _make_manager(_DiagnosticFailingIntentProvider("model-a"))

    intent = manager.generate_intent("hello", [], "system")

    assert intent.action == "error"
    assert intent.state_summary["provider_used"] == "provider_1"
    assert intent.state_summary["provider_parse_status"] == "missing_response_text"
    assert intent.state_summary["provider_fallback_reason"] == "provider_contract_error"
    assert intent.state_summary["error_stage"] == "llm_manager"
    assert intent.state_summary["error_type"] == "provider_contract_error"
    assert intent.state_summary["diagnostic_source"] == "openrouter"
    assert intent.state_summary["raw_preview"]
    assert intent.state_summary["raw_preview_truncated"] is False
    assert intent.state_summary["raw_preview_chars"] >= len(intent.state_summary["raw_preview"])
    meta = manager.get_last_router_meta()
    assert meta["provider_parse_status"] == "missing_response_text"
    assert meta["provider_fallback_reason"] == "provider_contract_error"
    assert meta["error_stage"] == "provider"


def test_generate_text_rejects_blank_success_and_emits_manager_diagnostics():
    manager = _make_manager(_WhitespaceTextProvider("model-a"))

    with pytest.raises(ProviderContractError) as excinfo:
        manager.generate_text("hello", "system")

    details = excinfo.value.details
    assert details["error_stage"] == "llm_manager"
    assert details["error_type"] == "manager_empty_output"
    assert details["error_reason"] == "generate_text_returned_empty"
    assert details["semantic_authority"] is False
    assert details["provider_used"] == "provider_1"
    assert details["provider_parse_status"] == "ok"
    assert details["raw_preview_chars"] == 0
