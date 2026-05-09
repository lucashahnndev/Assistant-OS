import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.services.context import ContextBroker, ContextIntent, IntentClassifier, RetrievalRouter
from src.services.context.models import ContextBundle, ContextDiagnostics, EvidenceItem
from src.services.llm.prompt_composer import PromptComposer


class _FakeCapabilityRegistry:
    def get_focus_actions(self, user_input: str, allowed_actions=None, limit: int = 3):
        return [
            {
                "id": "system.control.capabilities.describe",
                "description": "Describe a capability and its parameters.",
                "score": 0.91,
            }
        ][:limit]

    def get_action_metadata(self, action_id: str):
        return {
            "description": "Describe a capability and its parameters.",
            "risk_level": "low",
            "side_effect": "none",
            "permissions": {"approval_modes": ["none"]},
            "namespace": "system.control",
            "capability_id": "system_control",
        }


def _session(**overrides):
    base = {
        "session_id": "s1",
        "memory": [],
        "context": {"user_language": "en"},
        "pending_action": None,
        "task_registry": {},
        "active_focus_task_id": None,
        "summary": "",
        "turn_id": 3,
        "state_summary": {"last_error": "None"},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_intent_classifier_maps_memory_and_capability_queries():
    classifier = IntentClassifier()
    memory_intent, _ = classifier.classify("Do you remember what I said last time?", session=_session())
    capability_intent, _ = classifier.classify("How do I use the browser tool?", session=_session())
    weather_intent, _ = classifier.classify("como está o clima?", session=_session())
    calendar_intent, _ = classifier.classify("como está a minha agenda?", session=_session())

    assert memory_intent == ContextIntent.MEMORY_LOOKUP
    assert capability_intent == ContextIntent.CAPABILITY_LOOKUP
    assert weather_intent == ContextIntent.TASK_EXECUTION
    assert calendar_intent == ContextIntent.TASK_EXECUTION


def test_retrieval_router_exposes_phase1_domains_without_entrenching_store_details():
    router = RetrievalRouter()
    targets = router.route(ContextIntent.TASK_EXECUTION, user_input="implement a task")
    domains = [target.domain for target in targets]

    assert domains == [
        "procedures",
        "capability_knowledge",
        "user_memory",
        "agent_experience",
        "custom_knowledge",
        "external_knowledge",
        "policies",
    ]
    assert any(target.domain == "agent_experience" and target.active is False for target in targets)
    assert any(target.domain == "custom_knowledge" and target.active is False for target in targets)
    assert any(target.domain == "external_knowledge" and target.active is False for target in targets)
    assert any(target.domain == "policies" and target.active is False for target in targets)


def test_context_broker_builds_normalized_evidence_and_diagnostics():
    broker = ContextBroker(retrieval_handlers=ContextBroker.default_handlers())
    session = _session(
        memory=[
            {
                "id": "m1",
                "content": "The user prefers concise implementation reports.",
                "category": "preference",
                "confidence": 0.9,
            }
        ]
    )

    bundle = broker.build_bundle(
        user_input="How do I use the capability system?",
        session=session,
        capability_registry=_FakeCapabilityRegistry(),
        allowed_actions=["system.control.capabilities.describe"],
        situational_context={"channel": "web"},
        session_context={"turn_id": 3},
    )

    assert bundle.diagnostics.intent == ContextIntent.CAPABILITY_LOOKUP.value
    assert "capability_knowledge" in bundle.diagnostics.selected_targets
    assert bundle.diagnostics.evidence_count >= 1
    assert any(item.domain == "capability_knowledge" for item in bundle.evidence_items)


def test_context_broker_routes_calendar_queries_as_task_execution():
    broker = ContextBroker(retrieval_handlers=ContextBroker.default_handlers())
    session = _session()

    bundle = broker.build_bundle(
        user_input="como está a minha agenda?",
        session=session,
        capability_registry=_FakeCapabilityRegistry(),
        allowed_actions=["calendar.list_events", "calendar.get_event"],
        situational_context={"channel": "web"},
        session_context={"turn_id": 4},
    )

    assert bundle.diagnostics.intent == ContextIntent.TASK_EXECUTION.value
    assert "capability_knowledge" in bundle.diagnostics.selected_targets


def test_prompt_composer_includes_optional_broker_evidence_block():
    pc = PromptComposer()
    prompt = pc.compose(
        agent_name="Atlas",
        personality="You are practical.",
        specialist_prompt="",
        presentation_directive="[PRESENTATION DIRECTIVE]\n- concise",
        instruction_pack="",
        sys_info={"date": "2026-03-13", "time": "01:00:00", "os": "Linux", "user": "lucas"},
        location="Unknown",
        channel="web",
        user_name="admin",
        user_language="en",
        toon_state="{}",
        toon_deltas=[],
        user_input="How do I use the capability system?",
        project_path="/tmp/project",
        workspace_path="/tmp/workspace",
        venv_python="/tmp/env/bin/python",
        venv_pip="/tmp/env/bin/pip",
        browser_pages=[],
        session_summary="",
        scratchpad="",
        attachments=[],
        capabilities_summary="- `system.control.capabilities.describe`: ...",
        capability_scope="principal-filtered",
        context_bundle=ContextBundle(
            situational_context={"channel": "web"},
            session_context={"turn_id": 4},
            evidence_items=[
                EvidenceItem(
                    domain="capability_knowledge",
                    title="system.control.capabilities.describe",
                    content="Describes a capability and its parameters.",
                    source="capability_registry:system.control.capabilities.describe",
                    score=0.91,
                )
            ],
            diagnostics=ContextDiagnostics(
                intent="capability_lookup",
                selected_targets=["capability_knowledge"],
                evidence_domains=["capability_knowledge"],
                evidence_count=1,
            ),
        ),
    )

    assert "[CONTEXT EVIDENCE]" in prompt
    assert "[EVIDENCE: capability_knowledge]" in prompt
    assert "system.control.capabilities.describe" in prompt
