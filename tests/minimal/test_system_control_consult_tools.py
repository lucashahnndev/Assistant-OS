import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.capabilities.system_control.capability import SystemCapability
from src.core.orchestrator import AgentOrchestrator
from src.services.llm.prompt_composer import PromptComposer
from src.utils.toon_codec import encode_state_summary


class _FakeRegistry:
    def list_discovery_offers(self, **kwargs):
        return [
            {
                "capability_id": "calendar",
                "namespace": "calendar",
                "kind": "discoverability",
                "roles": ["search", "retrieve", "control"],
                "domains": ["calendar", "agenda", "schedule"],
                "entity_types": ["event", "appointment", "agenda"],
                "keywords": ["agenda", "calendario", "calendário", "eventos"],
                "actions": ["calendar.list_events", "calendar.get_event"],
                "setup_ready": True,
            },
            {
                "capability_id": "browser_control",
                "namespace": "browser.control",
                "kind": "discoverability",
                "roles": ["search", "control"],
                "domains": ["browser", "web"],
                "entity_types": ["page", "ui"],
                "keywords": ["browser", "site", "web", "tela"],
                "actions": ["browser.control.run", "browser.control.close"],
                "setup_ready": True,
            },
            {
                "capability_id": "weather_control",
                "namespace": "weather.control",
                "kind": "discoverability",
                "roles": ["search", "retrieve"],
                "domains": ["weather"],
                "entity_types": ["weather_report"],
                "keywords": ["clima", "tempo", "weather"],
                "actions": ["weather.control.get", "weather.control.forecast"],
                "setup_ready": True,
            },
        ]

    def list_retrieval_offers(self, **kwargs):
        return [
            {
                "capability_id": "browser_control",
                "namespace": "browser.control",
                "roles": ["search", "control"],
                "domains": ["browser", "web"],
                "entity_types": ["page", "ui"],
                "actions": ["browser.control.run", "browser.control.close"],
                "setup_ready": True,
            },
            {
                "capability_id": "weather_control",
                "namespace": "weather.control",
                "roles": ["search", "retrieve"],
                "domains": ["weather"],
                "entity_types": ["weather_report"],
                "actions": ["weather.control.get", "weather.control.forecast"],
                "setup_ready": True,
            }
        ]

    def get_focus_actions(self, user_input: str, allowed_actions=None, limit: int = 8):
        return [
            {
                "id": "weather.control.get",
                "description": "Fetch current weather conditions.",
                "score": 0.95,
            },
            {
                "id": "memory_management.recall",
                "description": "Recall a stored fact or memory.",
                "score": 0.12,
            },
        ][:limit]

    def get_action_metadata(self, action_id: str):
        return {
            "title": "Fetch current weather",
            "description": "Fetch current weather conditions.",
            "risk_level": "low",
            "capability_id": "weather_control",
            "namespace": "weather.control",
        }

    def list_actions(self):
        return ["system.control.consult_tools", "weather.control.get", "memory_management.recall"]


def test_system_control_consult_tools_returns_semantic_candidates():
    class _FakeBroker:
        def build_bundle(self, **kwargs):
            return SimpleNamespace(
                diagnostics=SimpleNamespace(
                    intent="task_execution",
                    evidence_domains=["weather"],
                )
            )

    kernel = SimpleNamespace(orchestrator=SimpleNamespace(capability_registry=_FakeRegistry(), context_broker=_FakeBroker()))
    capability = SystemCapability(kernel=kernel)

    result = capability.execute(
        "system.control.consult_tools",
        {
            "query": "como está o clima?",
            "domain": "weather",
            "intent": "task_execution",
            "limit": 3,
            "format": "legacy",
        },
        {"allowed_actions": ["weather.control.get", "memory_management.recall", "system.control.consult_tools"]},
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["count"] >= 1
    assert result["items"][0]["action_id"] == "weather.control.get"
    assert result["items"][0]["capability_id"] == "weather_control"
    assert result["items"][0]["source"] in {"retrieval_offer", "focus_ranker"}
    assert result["intent"] == "task_execution"
    assert result["broker_domains"] == ["weather"]
    assert result["primary_action_id"] == "weather.control.get"
    assert result["primary_score"] is not None


def test_system_control_consult_tools_falls_back_to_current_user_input():
    class _FakeBroker:
        def build_bundle(self, **kwargs):
            return SimpleNamespace(
                diagnostics=SimpleNamespace(
                    intent="task_execution",
                    evidence_domains=["weather"],
                )
            )

    kernel = SimpleNamespace(orchestrator=SimpleNamespace(capability_registry=_FakeRegistry(), context_broker=_FakeBroker()))
    capability = SystemCapability(kernel=kernel)

    result = capability.execute(
        "system.control.consult_tools",
        {
            "domain": "weather",
            "intent": "task_execution",
            "limit": 3,
            "format": "legacy",
        },
        {
            "user_input": "como está o clima?",
            "allowed_actions": ["weather.control.get", "memory_management.recall", "system.control.consult_tools"],
        },
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["query"] == "como está o clima?"
    assert result["items"][0]["action_id"] == "weather.control.get"
    assert result["primary_action_id"] == "weather.control.get"


def test_system_control_consult_tools_downranks_browser_for_information_queries():
    class _FakeBroker:
        def build_bundle(self, **kwargs):
            return SimpleNamespace(
                diagnostics=SimpleNamespace(
                    intent="task_execution",
                    evidence_domains=["capability_knowledge", "procedures"],
                )
            )

    kernel = SimpleNamespace(orchestrator=SimpleNamespace(capability_registry=_FakeRegistry(), context_broker=_FakeBroker()))
    capability = SystemCapability(kernel=kernel)

    result = capability.execute(
        "system.control.consult_tools",
        {
            "query": "como está o clima?",
            "domain": "weather",
            "intent": "task_execution",
            "limit": 4,
            "format": "legacy",
        },
        {"allowed_actions": ["browser.control.run", "browser.control.close", "weather.control.get", "system.control.consult_tools"]},
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["items"][0]["action_id"] == "weather.control.get"
    assert result["primary_action_id"] == "weather.control.get"


def test_system_control_consult_tools_keeps_browser_for_explicit_browser_requests():
    class _FakeBroker:
        def build_bundle(self, **kwargs):
            return SimpleNamespace(
                diagnostics=SimpleNamespace(
                    intent="task_execution",
                    evidence_domains=["browser"],
                )
            )

    kernel = SimpleNamespace(orchestrator=SimpleNamespace(capability_registry=_FakeRegistry(), context_broker=_FakeBroker()))
    capability = SystemCapability(kernel=kernel)

    result = capability.execute(
        "system.control.consult_tools",
        {
            "query": "abra o navegador e pesquise um site",
            "domain": "browser",
            "intent": "task_execution",
            "limit": 4,
            "format": "legacy",
        },
        {"allowed_actions": ["browser.control.run", "browser.control.close", "weather.control.get", "system.control.consult_tools"]},
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["items"][0]["action_id"] == "browser.control.run"
    assert result["primary_action_id"] == "browser.control.run"


def test_system_control_consult_tools_prefers_calendar_discovery_for_agenda_queries():
    class _FakeBroker:
        def build_bundle(self, **kwargs):
            return SimpleNamespace(
                diagnostics=SimpleNamespace(
                    intent="task_execution",
                    evidence_domains=["calendar"],
                )
            )

    kernel = SimpleNamespace(orchestrator=SimpleNamespace(capability_registry=_FakeRegistry(), context_broker=_FakeBroker()))
    capability = SystemCapability(kernel=kernel)

    result = capability.execute(
        "system.control.consult_tools",
        {
            "query": "como está a minha agenda?",
            "domain": "calendar",
            "intent": "task_execution",
            "limit": 4,
            "format": "legacy",
        },
        {"allowed_actions": ["calendar.list_events", "calendar.get_event", "browser.control.run", "system.control.consult_tools"]},
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["items"][0]["action_id"] == "calendar.list_events"
    assert result["primary_action_id"] == "calendar.list_events"


def test_system_control_consult_tools_prefers_internal_calendar_over_google_calendar_for_agenda_queries():
    class _FakeBroker:
        def build_bundle(self, **kwargs):
            return SimpleNamespace(
                diagnostics=SimpleNamespace(
                    intent="task_execution",
                    evidence_domains=["calendar"],
                )
            )

    class _CalendarRegistry(_FakeRegistry):
        def list_discovery_offers(self, **kwargs):
            return [
                {
                    "capability_id": "calendar",
                    "namespace": "calendar",
                    "kind": "discoverability",
                    "roles": ["search", "retrieve", "control"],
                    "domains": ["calendar", "agenda", "schedule"],
                    "entity_types": ["event", "appointment", "agenda"],
                    "keywords": ["agenda", "calendario", "calendário", "eventos"],
                    "actions": ["calendar.list_events", "calendar.get_event"],
                    "setup_ready": True,
                },
                {
                    "capability_id": "google_calendar",
                    "namespace": "google.calendar",
                    "kind": "discoverability",
                    "roles": ["search", "retrieve", "control"],
                    "domains": ["calendar", "google_calendar", "sync"],
                    "entity_types": ["event", "appointment", "agenda", "calendar_account"],
                    "keywords": ["google calendar", "google agenda", "sync", "account"],
                    "actions": ["google.calendar.sync", "google.calendar.list_calendars"],
                    "setup_ready": True,
                },
            ]

    kernel = SimpleNamespace(orchestrator=SimpleNamespace(capability_registry=_CalendarRegistry(), context_broker=_FakeBroker()))
    capability = SystemCapability(kernel=kernel)

    result = capability.execute(
        "system.control.consult_tools",
        {
            "query": "como está a minha agenda?",
            "domain": "calendar",
            "intent": "task_execution",
            "limit": 4,
            "format": "legacy",
        },
        {"allowed_actions": ["calendar.list_events", "google.calendar.sync", "google.calendar.list_calendars", "system.control.consult_tools"]},
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert "message" not in result
    assert result["items"][0]["action_id"] == "calendar.list_events"
    assert result["primary_action_id"] == "calendar.list_events"
    assert all(item["action_id"] != "google.calendar.sync" for item in result["items"][:1])


def test_system_control_consult_tools_discourages_task_scheduler_for_internal_agenda_queries():
    class _FakeBroker:
        def build_bundle(self, **kwargs):
            return SimpleNamespace(
                diagnostics=SimpleNamespace(
                    intent="task_execution",
                    evidence_domains=["calendar"],
                )
            )

    class _CalendarTaskRegistry(_FakeRegistry):
        def list_discovery_offers(self, **kwargs):
            return [
                {
                    "capability_id": "task_management",
                    "namespace": "task.scheduler",
                    "kind": "discoverability",
                    "roles": ["control", "search", "retrieve"],
                    "domains": ["tasks", "scheduler", "workflow"],
                    "entity_types": ["task", "trigger", "run"],
                    "keywords": ["task", "scheduler", "workflow", "trigger", "job", "queue", "plan", "work"],
                    "actions": ["task.scheduler.run", "task.scheduler.list"],
                    "setup_ready": True,
                },
                {
                    "capability_id": "calendar",
                    "namespace": "calendar",
                    "kind": "discoverability",
                    "roles": ["search", "retrieve", "control"],
                    "domains": ["calendar", "agenda", "schedule"],
                    "entity_types": ["event", "appointment", "agenda"],
                    "keywords": ["agenda", "calendario", "calendário", "eventos"],
                    "actions": ["calendar.list_events", "calendar.get_event"],
                    "setup_ready": True,
                },
            ]

    kernel = SimpleNamespace(orchestrator=SimpleNamespace(capability_registry=_CalendarTaskRegistry(), context_broker=_FakeBroker()))
    capability = SystemCapability(kernel=kernel)

    result = capability.execute(
        "system.control.consult_tools",
        {
            "query": "como está a minha agenda?",
            "domain": "calendar",
            "intent": "task_execution",
            "limit": 4,
            "format": "legacy",
        },
        {"allowed_actions": ["task.scheduler.run", "task.scheduler.list", "calendar.list_events", "calendar.get_event", "system.control.consult_tools"]},
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert "message" not in result
    assert result["items"][0]["action_id"] == "calendar.list_events"
    assert result["primary_action_id"] == "calendar.list_events"
    assert all(item["action_id"] != "task.scheduler.run" for item in result["items"][:1])


def test_system_control_consult_tools_prefers_capability_knowledge_rag_over_browser_fallback():
    evidence_item = SimpleNamespace(
        domain="capability_knowledge",
        title="Calendar list events",
        content="Capability calendar. Action calendar.list_events. Description: list events in the user's calendar.",
        source="capability_knowledge",
        metadata={
            "capability_id": "calendar",
            "action_id": "calendar.list_events",
            "doc_type": "capability_action",
            "namespace": "calendar",
            "title": "List events",
            "description": "List events in the user's calendar.",
        },
        score=0.98,
        provenance=["capability_knowledge"],
    )

    class _FakeBroker:
        def build_bundle(self, **kwargs):
            return SimpleNamespace(
                diagnostics=SimpleNamespace(
                    intent="task_execution",
                    evidence_domains=["capability_knowledge"],
                ),
                evidence_items=[evidence_item],
            )

    class _BrowserOnlyRegistry(_FakeRegistry):
        def list_discovery_offers(self, **kwargs):
            return [
                {
                    "capability_id": "browser_control",
                    "namespace": "browser.control",
                    "kind": "discoverability",
                    "roles": ["search", "control"],
                    "domains": ["browser", "web"],
                    "entity_types": ["page", "ui"],
                    "keywords": ["browser", "site", "web", "tela"],
                    "actions": ["browser.control.run", "browser.control.close"],
                    "setup_ready": True,
                },
            ]

    kernel = SimpleNamespace(orchestrator=SimpleNamespace(capability_registry=_BrowserOnlyRegistry(), context_broker=_FakeBroker()))
    capability = SystemCapability(kernel=kernel)

    result = capability.execute(
        "system.control.consult_tools",
        {
            "query": "como está a minha agenda?",
            "domain": "calendar",
            "intent": "task_execution",
            "limit": 4,
            "format": "legacy",
        },
        {"allowed_actions": ["calendar.list_events", "browser.control.run", "system.control.consult_tools"]},
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["discovery_source"] == "capability_knowledge_rag"
    assert result["items"][0]["action_id"] == "calendar.list_events"
    assert result["items"][0]["source"] == "capability_knowledge_rag"
    assert result["primary_action_id"] == "calendar.list_events"


def test_prompt_actions_block_keeps_only_consult_tools_in_on_demand_chat_mode():
    orchestrator = object.__new__(AgentOrchestrator)
    orchestrator.config_manager = SimpleNamespace(
        get=lambda key, default=None: {"actions_mode": "on_demand", "actions_pack_style": "compact_json"} if key == "prompt_context" else default
    )
    orchestrator.capability_registry = SimpleNamespace(list_actions=lambda: ["system.control.consult_tools"])

    block = AgentOrchestrator._build_prompt_actions_block(
        orchestrator,
        user_input="oi",
        allowed_actions=["system.control.consult_tools"],
    )

    assert "system.control.consult_tools" in block
    assert "system.control.capabilities.list.ai" not in block
    assert "system.control.capabilities.describe.ai" not in block
    assert "m=od_chat" in block


def test_state_summary_encodes_tool_discovery_for_followup_prompt():
    toon = encode_state_summary(
        {
            "goal": "find weather tool",
            "last_tool_discovery": {
                "query": "como está o clima?",
                "intent": "task_execution",
                "domain": "weather",
                "role": "search",
                "entity_type": "weather_report",
                "count": 2,
            },
            "tool_candidates": ["weather.control.get", "weather.control.forecast"],
        }
    )

    assert toon["td"]["q"] == "como está o clima?"
    assert toon["td"]["d"] == "weather"
    assert toon["td"]["a"] == ["weather.control.get", "weather.control.forecast"]
    assert toon["td"]["n"] == 2

    composer = PromptComposer()
    state_payload = encode_state_summary(
        {
            "goal": "find weather tool",
            "last_tool_discovery": {
                "query": "como está o clima?",
                "intent": "task_execution",
                "domain": "weather",
                "role": "search",
                "entity_type": "weather_report",
                "count": 2,
            },
            "tool_candidates": ["weather.control.get", "weather.control.forecast"],
        }
    )
    prompt = composer.compose(
        agent_name="Atlas",
        personality="You are practical.",
        specialist_prompt="",
        presentation_directive="[PRESENTATION DIRECTIVE]\n- concise",
        instruction_pack="",
        sys_info={"date": "2026-03-22", "time": "12:00:00", "os": "Linux", "user": "lucas"},
        location="Unknown",
        channel="web",
        user_name="lucas",
        user_language="pt-BR",
        toon_state=json.dumps(state_payload, ensure_ascii=False, separators=(",", ":")),
        toon_deltas=[],
        user_input="como está o clima?",
        project_path="/tmp/project",
        workspace_path="/tmp/workspace",
        venv_python="/tmp/env/bin/python",
        venv_pip="/tmp/env/bin/pip",
        browser_pages=[],
        session_summary="",
        scratchpad="",
        attachments=[],
        capabilities_summary="m=od\n{\"v\":\"ac.v4\",\"m\":\"od\",\"d\":[\"system.control.consult_tools\"],\"r\":[\"discover\",\"consult_first\",\"semantic_index\"]}",
        capability_scope="principal-filtered",
    )

    assert "[TOON STATE]" in prompt
    assert "last_tool_discovery" in prompt
    assert "[TOOL DISCOVERY]" not in prompt
    assert "weather.control.get" in prompt
    assert "weather.control.forecast" in prompt
