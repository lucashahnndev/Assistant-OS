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
    memory_classification = classifier.classify("Do you remember what I said last time?", session=_session())
    capability_classification = classifier.classify("How do I use the browser tool?", session=_session())

    memory_intent, memory_notes = memory_classification
    capability_intent, capability_notes = capability_classification

    assert memory_classification.legacy_intent == ContextIntent.MEMORY_LOOKUP
    assert capability_classification.legacy_intent == ContextIntent.CAPABILITY_LOOKUP
    assert memory_classification.semantic_authority is False
    assert capability_classification.semantic_authority is False
    assert memory_intent == ContextIntent.MEMORY_LOOKUP
    assert capability_intent == ContextIntent.CAPABILITY_LOOKUP
    assert memory_notes == memory_classification.hints
    assert capability_notes == capability_classification.hints
    assert "memory_markers" in memory_notes
    assert "capability_markers" in capability_notes


def test_retrieval_router_exposes_phase1_domains_without_entrenching_store_details():
    router = RetrievalRouter()
    route_signals = router.route(ContextIntent.TASK_EXECUTION, user_input="implement a task")
    targets = route_signals.targets
    domains = [target.domain for target in route_signals]

    assert route_signals.legacy_intent == ContextIntent.TASK_EXECUTION
    assert route_signals.semantic_authority is False
    assert domains == [
        "procedures",
        "capability_knowledge",
        "user_memory",
        "agent_experience",
        "custom_knowledge",
        "external_knowledge",
        "mcp_resources",
        "policies",
    ]
    assert route_signals.candidate_domains == domains
    assert route_signals.reasons[0] == "intent:task_execution"
    assert "legacy_intent:task_execution" in route_signals.source_hints
    assert route_signals.domain_weights["procedures"] > route_signals.domain_weights["policies"]
    assert any(target.domain == "agent_experience" and target.active is False for target in targets)
    assert any(target.domain == "custom_knowledge" and target.active is False for target in targets)
    assert any(target.domain == "external_knowledge" and target.active is False for target in targets)
    assert any(target.domain == "mcp_resources" and target.active is False for target in targets)
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

    assert "[BROKER EVIDENCE]" in prompt
    assert "[EVIDENCE: capability_knowledge]" in prompt
    assert "system.control.capabilities.describe" in prompt
