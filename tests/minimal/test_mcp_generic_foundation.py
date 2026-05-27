import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.services.mcp.bridge import MCPToolAdapter
from src.services.mcp.client import MCPClientManager
from src.services.mcp.models import MCPServerConfig, MCPToolDescriptor
from src.services.mcp.policy import MCPPolicyGate
from src.services.mcp.registry import MCPServerRegistry


class _FakeTransportClient:
    def __init__(self, tools=None):
        self._tools = list(tools or [])
        self.invocations = []
        self.closed = False

    def list_tools(self):
        return list(self._tools)

    def invoke_tool(self, tool_name, arguments):
        self.invocations.append((tool_name, dict(arguments or {})))
        return {"ok": True, "tool_name": tool_name, "arguments": dict(arguments or {})}

    def close(self):
        self.closed = True


def _server(**overrides):
    payload = {
        "id": "obsidian",
        "title": "Obsidian Vault",
        "enabled": True,
        "transport": {
            "kind": "http",
            "endpoint": "http://127.0.0.1:8765/mcp",
        },
        "policy": {
            "namespace": "mcp",
            "trust_tier": "partner",
            "tool_allowlist": ["search_notes", "read_note", "update_note"],
            "tool_denylist": ["delete_vault"],
        },
    }
    payload.update(overrides)
    return MCPServerConfig.model_validate(payload)


def test_mcp_server_registry_loads_and_filters_tools():
    registry = MCPServerRegistry()
    registry.load_from_config(
        {
            "servers": [
                _server().model_dump(),
                _server(id="github", title="GitHub", policy={"namespace": "mcp", "trust_tier": "trusted"}).model_dump(),
            ]
        }
    )

    enabled_ids = [server.id for server in registry.list_enabled()]
    assert enabled_ids == ["github", "obsidian"]
    assert registry.is_tool_allowed("obsidian", "search_notes") is True
    assert registry.is_tool_allowed("obsidian", "delete_vault") is False
    assert registry.is_tool_allowed("obsidian", "unlisted_tool") is False


def test_mcp_policy_gate_marks_mutations_and_untrusted_servers():
    gate = MCPPolicyGate()
    trusted_server = _server()
    read_tool = MCPToolDescriptor.model_validate(
        {
            "name": "read_note",
            "description": "Read one note",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            "annotations": {"readOnlyHint": True},
        }
    )
    write_tool = MCPToolDescriptor.model_validate(
        {
            "name": "update_note",
            "description": "Update one note",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            "annotations": {"readOnlyHint": False},
        }
    )
    untrusted_server = _server(policy={"namespace": "mcp", "trust_tier": "untrusted"})

    read_decision = gate.evaluate_tool(trusted_server, read_tool)
    write_decision = gate.evaluate_tool(trusted_server, write_tool)
    untrusted_decision = gate.evaluate_tool(untrusted_server, read_tool)

    assert read_decision.allowed is True
    assert read_decision.requires_approval is False
    assert read_decision.risk_level == "low"
    assert write_decision.requires_approval is True
    assert write_decision.risk_level == "medium"
    assert untrusted_decision.requires_approval is True
    assert untrusted_decision.risk_level == "medium"


def test_mcp_tool_adapter_builds_namespaced_actions():
    adapter = MCPToolAdapter()
    server = _server()
    tool = MCPToolDescriptor.model_validate(
        {
            "name": "search_notes",
            "title": "Search Notes",
            "description": "Search markdown notes in the vault",
            "input_schema": {"properties": {"query": {"type": "string"}}},
            "annotations": {"readOnlyHint": True},
        }
    )

    action = adapter.build_action_descriptor(server, tool)

    assert action is not None
    assert action.action_id == "mcp.obsidian.search_notes"
    assert action.parameters["type"] == "object"
    assert action.read_only is True
    assert action.metadata["origin"] == "mcp"


def test_mcp_client_manager_uses_transport_factories_and_caches_clients():
    server = _server()
    tool = MCPToolDescriptor.model_validate({"name": "search_notes"})
    client = _FakeTransportClient(tools=[tool])
    manager = MCPClientManager()
    manager.register_factory("http", lambda _server_cfg: client)

    listed = manager.list_tools(server)
    first = manager.invoke_tool(server, "search_notes", {"query": "atlas"})
    second = manager.invoke_tool(server, "search_notes", {"query": "obsidian"})
    manager.close("obsidian")

    assert [item.name for item in listed] == ["search_notes"]
    assert first["arguments"]["query"] == "atlas"
    assert second["arguments"]["query"] == "obsidian"
    assert len(client.invocations) == 2
    assert client.closed is True
