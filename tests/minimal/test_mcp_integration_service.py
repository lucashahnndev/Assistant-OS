import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.capabilities.registry import CapabilityRegistry
from src.services.mcp.client import MCPClientManager
from src.services.mcp.models import MCPToolDescriptor
from src.services.mcp.runtime import MCPIntegrationService


class _ConfigStub:
    def __init__(self, payload):
        self._payload = payload

    def get_mcp_config(self):
        return self._payload


class _FakeTransportClient:
    def __init__(self, tools=None):
        self._tools = list(tools or [])
        self.calls = []
        self.resource_calls = []
        self._resources = []

    def list_tools(self):
        return list(self._tools)

    def invoke_tool(self, tool_name, arguments):
        payload = {"tool_name": tool_name, "arguments": dict(arguments or {})}
        self.calls.append(payload)
        return payload

    def list_resources(self):
        return list(self._resources)

    def read_resource(self, resource_uri):
        payload = {"uri": str(resource_uri or ""), "contents": [{"uri": str(resource_uri or ""), "text": "resource body"}]}
        self.resource_calls.append(payload)
        return payload

    def close(self):
        return None


def test_mcp_integration_service_registers_dynamic_actions_and_dispatches():
    registry = CapabilityRegistry()
    client_manager = MCPClientManager()
    tool = MCPToolDescriptor.model_validate(
        {
            "name": "search_notes",
            "description": "Search notes inside the vault",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "annotations": {"readOnlyHint": True},
        }
    )
    fake_client = _FakeTransportClient(tools=[tool])
    client_manager.register_factory("http", lambda _server: fake_client)
    service = MCPIntegrationService(
        config_manager=_ConfigStub(
            {
                "enabled": True,
                "servers": [
                    {
                        "id": "obsidian",
                        "title": "Obsidian Vault",
                        "enabled": True,
                        "transport": {"kind": "http", "endpoint": "http://127.0.0.1:8765/mcp"},
                        "policy": {
                            "namespace": "mcp",
                            "trust_tier": "partner",
                            "tool_allowlist": ["search_notes"],
                        },
                    }
                ],
            }
        ),
        capability_registry=registry,
        client_manager=client_manager,
    )

    stats = service.refresh()
    metadata = registry.get_action_metadata("mcp.obsidian.search_notes")
    result = registry.dispatch("mcp.obsidian.search_notes", {"query": "atlas"}, {})

    assert stats["registered_actions"] == 1
    assert "mcp.obsidian.search_notes" in registry.list_actions()
    assert metadata["origin"] == "mcp"
    assert metadata["permissions"]["requires_approval"] is False
    assert result["ok"] is True
    assert result["data"]["tool_result"]["arguments"]["query"] == "atlas"
    assert fake_client.calls[0]["tool_name"] == "search_notes"


def test_mcp_integration_service_unregisters_actions_when_disabled():
    registry = CapabilityRegistry()
    client_manager = MCPClientManager()
    tool = MCPToolDescriptor.model_validate({"name": "search_notes", "annotations": {"readOnlyHint": True}})
    fake_client = _FakeTransportClient(tools=[tool])
    client_manager.register_factory("http", lambda _server: fake_client)

    enabled_service = MCPIntegrationService(
        config_manager=_ConfigStub(
            {
                "enabled": True,
                "servers": [
                    {
                        "id": "obsidian",
                        "title": "Obsidian Vault",
                        "enabled": True,
                        "transport": {"kind": "http", "endpoint": "http://127.0.0.1:8765/mcp"},
                        "policy": {"namespace": "mcp", "trust_tier": "partner"},
                    }
                ],
            }
        ),
        capability_registry=registry,
        client_manager=client_manager,
    )
    enabled_service.refresh()
    assert "mcp.obsidian.search_notes" in registry.list_actions()

    disabled_service = MCPIntegrationService(
        config_manager=_ConfigStub({"enabled": False, "servers": []}),
        capability_registry=registry,
        client_manager=client_manager,
    )
    stats = disabled_service.refresh()

    assert stats["enabled"] is False
    assert "mcp.obsidian.search_notes" not in registry.list_actions()


def test_mcp_integration_service_registers_resource_read_action():
    registry = CapabilityRegistry()
    client_manager = MCPClientManager()
    fake_client = _FakeTransportClient()
    fake_client._resources = [
        {
            "uri": "obsidian://note/a",
            "title": "Note A",
            "mime_type": "text/markdown",
        }
    ]
    from src.services.mcp.models import MCPResourceDescriptor

    fake_client._resources = [MCPResourceDescriptor.model_validate(item) for item in fake_client._resources]
    client_manager.register_factory("http", lambda _server: fake_client)
    service = MCPIntegrationService(
        config_manager=_ConfigStub(
            {
                "enabled": True,
                "servers": [
                    {
                        "id": "obsidian",
                        "title": "Obsidian Vault",
                        "enabled": True,
                        "transport": {"kind": "http", "endpoint": "http://127.0.0.1:8765/mcp"},
                        "policy": {
                            "namespace": "mcp",
                            "trust_tier": "partner",
                            "allow_resources": True,
                        },
                    }
                ],
            }
        ),
        capability_registry=registry,
        client_manager=client_manager,
    )

    stats = service.refresh()
    metadata = registry.get_action_metadata("mcp.obsidian.read_resource")
    result = registry.dispatch("mcp.obsidian.read_resource", {"uri": "obsidian://note/a"}, {})

    assert stats["servers_with_resources"] == 1
    assert "mcp.obsidian.read_resource" in registry.list_actions()
    assert metadata["permissions"]["requires_approval"] is False
    assert result["ok"] is True
    assert result["data"]["resource_result"]["contents"][0]["text"] == "resource body"
    assert fake_client.resource_calls[0]["uri"] == "obsidian://note/a"


def test_mcp_integration_service_retrieves_resources_as_context_items():
    registry = CapabilityRegistry()
    client_manager = MCPClientManager()
    fake_client = _FakeTransportClient()
    from src.services.mcp.models import MCPResourceDescriptor

    fake_client._resources = [
        MCPResourceDescriptor.model_validate(
            {
                "uri": "obsidian://note/atlas-mcp",
                "title": "Atlas MCP Notes",
                "description": "Integration design for atlas and obsidian",
                "mime_type": "text/markdown",
            }
        )
    ]
    client_manager.register_factory("http", lambda _server: fake_client)
    service = MCPIntegrationService(
        config_manager=_ConfigStub(
            {
                "enabled": True,
                "servers": [
                    {
                        "id": "obsidian",
                        "title": "Obsidian Vault",
                        "enabled": True,
                        "transport": {"kind": "http", "endpoint": "http://127.0.0.1:8765/mcp"},
                        "policy": {
                            "namespace": "mcp",
                            "trust_tier": "partner",
                            "allow_resources": True,
                        },
                    }
                ],
            }
        ),
        capability_registry=registry,
        client_manager=client_manager,
    )

    service.refresh()
    items = service.retrieve_resources(query="atlas obsidian integration", max_results=3)

    assert len(items) == 1
    assert items[0]["title"] == "Atlas MCP Notes"
    assert items[0]["metadata"]["origin"] == "mcp_resource"
    assert items[0]["content"] == "resource body"
