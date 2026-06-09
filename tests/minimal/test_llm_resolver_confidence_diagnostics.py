import sys
from pathlib import Path
from types import SimpleNamespace

from core.errors import ErrorCode

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.core.resolution.llm_resolver import LLMResolver


class _FakeIntent:
    def __init__(self, *, action: str, params, response_text: str, thought: str, plan=None):
        self.action = action
        self.params = params
        self.response_text = response_text
        self.thought = thought
        self.attachments = []
        self.plan = plan if plan is not None else []
        self.state_summary = {}
        self.task_label = None
        self.model_used = "stub"


class _FakeLLMManager:
    def __init__(self, intent):
        self._intent = intent

    def get_active_config(self):
        return {"max_context": 8000}

    def generate_intent(self, *args, **kwargs):
        return self._intent


class _Registry:
    def resolve_action_id(self, action_id):
        return action_id

    def get_capability_for_action(self, action_id):
        return object() if action_id == "demo.action" else None


class _Session:
    def __init__(self):
        self.context = {"user_language": "pt-BR"}

    def get_context_for_llm(self, **kwargs):
        return []


def test_high_confidence_action_keeps_diagnostics_and_semantic_authority_false():
    intent = _FakeIntent(
        action="demo.action",
        params={"value": "ok"},
        response_text="",
        thought="planning a real action",
        plan=["step 1"],
    )
    resolver = LLMResolver(_FakeLLMManager(intent), threshold=0.65, capability_registry=_Registry())

    plan = resolver.resolve(
        "faça algo útil",
        {
            "session": _Session(),
            "allowed_actions": ["demo.action"],
            "capability_registry": _Registry(),
            "history": [],
            "system_prompt": "x",
        },
    )

    assert plan is not None
    assert plan.action_id == "demo.action"
    diagnostics = plan.metadata.get("confidence_diagnostics")
    assert diagnostics["semantic_authority"] is False
    assert diagnostics["score"] >= 0.65
    assert diagnostics["threshold"] == 0.65
    assert diagnostics["model_used"] == "stub"
    assert "action_allowed_for_principal" in diagnostics["reason_codes"]
    assert "params_present" in diagnostics["reason_codes"]
    assert "thought_present" in diagnostics["reason_codes"]
    assert "plan_present" in diagnostics["reason_codes"]
    assert plan.metadata.get("confidence_reason_codes")


def test_low_confidence_malformed_schema_exposes_structural_reason_codes():
    intent = _FakeIntent(
        action="demo.action",
        params=[],
        response_text="",
        thought="x",
        plan=[],
    )
    resolver = LLMResolver(_FakeLLMManager(intent), threshold=0.65, capability_registry=_Registry())

    plan = resolver.resolve(
        "faça algo útil",
        {
            "session": _Session(),
            "capability_registry": _Registry(),
            "history": [],
            "system_prompt": "x",
        },
    )

    assert plan is not None
    assert plan.action_id == "error"
    diagnostics = plan.metadata.get("confidence_diagnostics")
    assert diagnostics["semantic_authority"] is False
    assert diagnostics["score"] < 0.65
    assert diagnostics["threshold"] == 0.65
    assert diagnostics["model_used"] == "stub"
    assert "params_not_object" in diagnostics["reason_codes"]
    assert "thought_too_short" in diagnostics["reason_codes"]
    assert "schema" in diagnostics["reason_types"]
    assert "format" in diagnostics["reason_types"]
    assert plan.metadata.get("error_code") == "low_confidence"


def test_reply_without_text_is_rejected_with_schema_mismatch_diagnostics():
    intent = _FakeIntent(
        action="reply",
        params={},
        response_text="",
        thought="relevant thought",
        plan=[],
    )
    resolver = LLMResolver(_FakeLLMManager(intent), threshold=0.65, capability_registry=_Registry())

    plan = resolver.resolve(
        "responda de forma útil",
        {
            "session": _Session(),
            "capability_registry": _Registry(),
            "history": [],
            "system_prompt": "x",
        },
    )

    assert plan is not None
    assert plan.action_id == "error"
    diagnostics = plan.metadata.get("confidence_diagnostics")
    assert diagnostics["semantic_authority"] is False
    assert diagnostics["threshold"] == 0.65
    assert diagnostics["model_used"] == "stub"
    assert diagnostics["reason_codes"] == ["invalid_reply_payload"]
    assert "format" in diagnostics["reason_types"]
    assert plan.metadata.get("error_code") == ErrorCode.PLANNER_SCHEMA_MISMATCH.value
