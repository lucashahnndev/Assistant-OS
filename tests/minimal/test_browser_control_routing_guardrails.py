import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.core.orchestrator import AgentOrchestrator
from src.core.resolution.action_plan import ActionPlan
from src.services.llm.prompt_composer import PromptComposer


class _CapRegistry:
    def get_capability_for_action(self, action_id):
        if action_id in {"browser.control.run", "research.retrieve.run", "web.search.discover"}:
            return object()
        return None


class _Cfg:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=None):
        return self._values.get(key, default)


def _orchestrator():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.capability_registry = _CapRegistry()
    orchestrator.config_manager = _Cfg({"decision_policy": {"media_override_mode": "off"}})
    return orchestrator


def test_interactive_browser_request_does_not_trigger_on_informational_site_lookup():
    assert AgentOrchestrator._looks_like_interactive_browser_request("qual o site oficial da OpenAI?") is False


def test_interactive_browser_request_triggers_on_explicit_navigation():
    assert AgentOrchestrator._looks_like_interactive_browser_request("abra https://openai.com no navegador") is True


def test_media_policy_demotes_browser_for_non_interactive_research_query():
    orchestrator = _orchestrator()
    plan = ActionPlan(
        action_id="browser.control.run",
        args={"goal": "qual o site oficial da OpenAI?", "intent_class": "realizar_pesquisa"},
        confidence=0.91,
        source="llm",
    )

    rewritten = orchestrator._apply_media_decision_policy(
        session=None,
        user_input="qual o site oficial da OpenAI?",
        plan=plan,
        last_action_id=None,
        last_action_structured=None,
    )

    assert rewritten.action_id == "research.retrieve.run"
    assert rewritten.args == {"query": "qual o site oficial da OpenAI?"}


def test_media_policy_keeps_browser_for_explicit_ui_workflow():
    orchestrator = _orchestrator()
    plan = ActionPlan(
        action_id="browser.control.run",
        args={"goal": "abra o site do banco e clique em extrato", "intent_class": "automacao_ui"},
        confidence=0.91,
        source="llm",
    )

    rewritten = orchestrator._apply_media_decision_policy(
        session=None,
        user_input="abra o site do banco e clique em extrato",
        plan=plan,
        last_action_id=None,
        last_action_structured=None,
    )

    assert rewritten is plan


def test_prompt_policy_discourages_browser_for_lookup_tasks():
    policy = PromptComposer()._build_execution_policy()
    assert "Use browser actions only for explicit browser/UI interaction" in policy
    assert "Do NOT choose browser.control.run just because the request mentions web/site/search/browser/open" in policy
