import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.capabilities.base import CapabilityBase
from src.capabilities.contract_v1 import load_contract_v1
from src.capabilities.registry import CapabilityRegistry
from src.capabilities.system_control.capability import SystemCapability


class _DummyCapability(CapabilityBase):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def actions(self) -> List[str]:
        return ["dummy.search"]

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "status": "success"}


def test_registry_exposes_discovery_metadata_without_routing_it():
    registry = CapabilityRegistry()
    capability = _DummyCapability()

    registry.register_dynamic_actions(
        source_id="dummy.source",
        capability=capability,
        actions=[
            {
                "action_id": "dummy.search",
                "title": "Search dummy data",
                "description": "Search in dummy data sources.",
                "handler": "dummy.search",
                "risk_level": "low",
                "permissions": {
                    "scopes": ["dummy.read"],
                    "allow_anyone": True,
                    "requires_approval": False,
                },
                "parameters": {"type": "object", "properties": {}},
                "examples": [{"input": {"query": "abc"}, "output": {"ok": True}}],
                "side_effect": "read_only",
                "ui_hints": {"icon": "search"},
                "when_to_use": "When the request is a lookup inside the dummy data set.",
                "when_not_to_use": "Do not use for task execution or write operations.",
                "required_context": ["query"],
                "common_failures": ["No matching records"],
                "repair_hints": ["Ask for a narrower query if the result is empty."],
            }
        ],
    )

    meta = registry.get_action_metadata("dummy.search")
    assert meta["id"] == "dummy.search"
    assert meta["side_effect"] == "read_only"
    assert meta["examples"]
    assert meta["ui_hints"] == {"icon": "search"}
    assert meta["when_to_use"].startswith("When the request")
    assert meta["when_not_to_use"].startswith("Do not use")
    assert meta["required_context"] == ["query"]
    assert meta["common_failures"] == ["No matching records"]
    assert meta["repair_hints"] == ["Ask for a narrower query if the result is empty."]
    assert meta["semantic_authority"] is False
    assert meta["metadata_role"] == "documentation"
    assert meta["decision_owner"] == "agent"
    assert meta["discovery"]["when_to_use"] == meta["when_to_use"]
    assert meta["discovery"]["examples"] == meta["examples"]
    assert meta["discovery"]["semantic_authority"] is False
    assert meta["discovery"]["metadata_role"] == "documentation"
    assert meta["discovery"]["decision_owner"] == "agent"

    catalog = registry.get_catalog(allowed_actions=["dummy.search"], include_descriptions=True)
    assert catalog == [
        {
            "id": "dummy.search",
            "namespace": "dummy",
            "risk_level": "low",
            "capability_id": "dummy.source",
            "side_effect": "read_only",
            "requires_approval": False,
            "allow_anyone": True,
            "has_examples": True,
            "semantic_authority": False,
            "metadata_role": "documentation",
            "decision_owner": "agent",
            "description": "Search in dummy data sources.",
        }
    ]

    summary = registry.get_summary(allowed_actions=["dummy.search"])
    assert "side_effect=read_only" in summary


def test_registry_exposes_real_contract_discovery_metadata_for_browser_and_overlay():
    class _ContractCapability(CapabilityBase):
        def __init__(self, name: str, actions: List[str]):
            self._name = name
            self._actions = actions

        @property
        def name(self) -> str:
            return self._name

        @property
        def actions(self) -> List[str]:
            return self._actions

        def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            return {"ok": True, "status": "success"}

    registry = CapabilityRegistry()

    browser_contract = load_contract_v1(str(ROOT / "src/capabilities/browser_control/contract.json"))
    browser_capability = _ContractCapability(
        browser_contract.capability.id,
        [action.id for action in browser_contract.actions],
    )
    registry.register(browser_capability, browser_contract)

    overlay_contract = load_contract_v1(str(ROOT / "src/capabilities/assistive_overlay/contract.json"))
    overlay_capability = _ContractCapability(
        overlay_contract.capability.id,
        [action.id for action in overlay_contract.actions],
    )
    registry.register(overlay_capability, overlay_contract)

    browser_meta = registry.get_action_metadata("browser.control.run")
    assert browser_meta["capability_description"].startswith("Controla um navegador real")
    assert browser_meta["when_to_use"].startswith("Quando uma interação real")
    assert "goal" in browser_meta["required_context"]
    assert "site_or_url_if_known" in browser_meta["required_context"]
    assert browser_meta["common_failures"]
    assert browser_meta["repair_hints"]
    assert browser_meta["examples"]
    assert browser_meta["ui_hints"] == {"icon": "browser", "surface": "chrome"}
    assert browser_meta["discovery"]["when_not_to_use"].startswith("Quando basta explicação textual")
    assert browser_meta["semantic_authority"] is False
    assert browser_meta["metadata_role"] == "documentation"
    assert browser_meta["decision_owner"] == "agent"

    overlay_meta = registry.get_action_metadata("overlay.assist.highlight_target")
    assert overlay_meta["when_to_use"].startswith("Quando o agente já decidiu ajudar visualmente")
    assert "label" in overlay_meta["required_context"]
    assert overlay_meta["common_failures"]
    assert overlay_meta["repair_hints"]
    assert overlay_meta["examples"]
    assert overlay_meta["ui_hints"] == {"icon": "highlight", "surface": "screen"}
    assert overlay_meta["semantic_authority"] is False
    assert overlay_meta["metadata_role"] == "documentation"
    assert overlay_meta["decision_owner"] == "agent"

    ddg_contract = load_contract_v1(str(ROOT / "src/capabilities/ddg_search/contract.json"))
    ddg_capability = _ContractCapability(
        ddg_contract.capability.id,
        [action.id for action in ddg_contract.actions],
    )
    registry.register(ddg_capability, ddg_contract)

    offers = registry.list_discovery_offers(domain="web", role="search", entity_type="article")
    offer_ids = {row["capability_id"] for row in offers}
    assert "ddg_search" in offer_ids
    ddg_offer = next(row for row in offers if row["capability_id"] == "ddg_search")
    assert ddg_offer["semantic_authority"] is False
    assert ddg_offer["metadata_role"] == "documentation"
    assert ddg_offer["decision_owner"] == "agent"

    catalog = registry.get_catalog(allowed_actions=["browser.control.run", "overlay.assist.highlight_target"], include_descriptions=True)
    rows_by_id = {row["id"]: row for row in catalog}
    assert rows_by_id["browser.control.run"]["side_effect"] == "idempotent"
    assert rows_by_id["browser.control.run"]["has_examples"] is True
    assert rows_by_id["browser.control.run"]["semantic_authority"] is False
    assert rows_by_id["browser.control.run"]["metadata_role"] == "documentation"
    assert rows_by_id["overlay.assist.highlight_target"]["side_effect"] == "none"
    assert rows_by_id["overlay.assist.highlight_target"]["requires_approval"] is False


def test_registry_exposes_real_contract_discovery_metadata_for_system_control_and_notifications():
    class _ContractCapability(CapabilityBase):
        def __init__(self, name: str, actions: List[str]):
            self._name = name
            self._actions = actions

        @property
        def name(self) -> str:
            return self._name

        @property
        def actions(self) -> List[str]:
            return self._actions

        def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            return {"ok": True, "status": "success"}

    registry = CapabilityRegistry()

    system_contract = load_contract_v1(str(ROOT / "src/capabilities/system_control/contract.json"))
    registry.register(
        _ContractCapability(system_contract.capability.id, [action.id for action in system_contract.actions]),
        system_contract,
    )

    notifications_contract = load_contract_v1(str(ROOT / "src/capabilities/notifications/contract.json"))
    registry.register(
        _ContractCapability(notifications_contract.capability.id, [action.id for action in notifications_contract.actions]),
        notifications_contract,
    )

    system_meta = registry.get_action_metadata("system.control.consult_tools")
    assert system_meta["capability_description"].startswith("Operações de controle do sistema")
    assert system_meta["when_to_use"].startswith("Quando o agente quer explorar quais ferramentas existem")
    assert "objective" in system_meta["required_context"]
    assert system_meta["common_failures"]
    assert system_meta["repair_hints"]
    assert system_meta["examples"]
    assert system_meta["ui_hints"] == {"icon": "search", "surface": "tool_catalog"}
    assert system_meta["semantic_authority"] is False
    assert system_meta["metadata_role"] == "documentation"
    assert system_meta["decision_owner"] == "agent"

    notifications_meta = registry.get_action_metadata("notifications.send")
    assert notifications_meta["capability_description"].startswith("Allows the agent to send formal notifications")
    assert notifications_meta["when_to_use"].startswith("Quando criar ou exibir uma notificação")
    assert "message" in notifications_meta["required_context"]
    assert notifications_meta["common_failures"]
    assert notifications_meta["repair_hints"]
    assert notifications_meta["examples"]
    assert notifications_meta["side_effect"] == "interruptive"
    assert notifications_meta["ui_hints"] == {"icon": "bell", "surface": "notification_center"}
    assert notifications_meta["semantic_authority"] is False
    assert notifications_meta["metadata_role"] == "documentation"
    assert notifications_meta["decision_owner"] == "agent"

    class _FakeBroker:
        def build_bundle(self, **kwargs):
            return SimpleNamespace(
                diagnostics=SimpleNamespace(
                    intent="tool_discovery",
                    evidence_domains=["system_control", "notifications"],
                ),
                evidence_items=[],
            )

    class _FakeLLMManager:
        def __init__(self):
            self.calls = []

        def generate_structured_text(self, prompt, system_prompt=None, **kwargs):
            self.calls.append({"prompt": prompt, "system_prompt": system_prompt or "", "kwargs": kwargs})
            payload = {
                "candidate_set": [
                    {
                        "action_id": "system.control.consult_tools",
                        "rank": 1,
                        "why": "discover tools",
                        "confidence": 0.95,
                    },
                    {
                        "action_id": "notifications.send",
                        "rank": 2,
                        "why": "notify user",
                        "confidence": 0.84,
                    },
                ],
                "primary_action_id": "system.control.consult_tools",
                "decision_summary": "use discovery then notify",
                "turns": 1,
            }
            return payload

    llm_manager = _FakeLLMManager()
    kernel = SimpleNamespace(
        orchestrator=SimpleNamespace(capability_registry=registry, context_broker=_FakeBroker(), llm_manager=llm_manager)
    )
    capability = SystemCapability(kernel=kernel)

    result = capability._agentic_consult_tools(
        query="quais ferramentas posso usar?",
        domain="system_control",
        intent="discovery",
        role="search",
        entity_type="tool",
        limit=2,
        context={
            "allowed_actions": ["system.control.consult_tools", "notifications.send"],
            "session": None,
        },
        registry=registry,
    )

    assert result["primary_action_id"] == "system.control.consult_tools"
    assert len(llm_manager.calls) >= 2
    second_prompt = llm_manager.calls[1]["prompt"]
    assert "tool_catalog" in second_prompt
    assert "notification_center" in second_prompt
    assert "when_to_use" in second_prompt
    assert "when_not_to_use" in second_prompt
    assert "repair_hints" in second_prompt
