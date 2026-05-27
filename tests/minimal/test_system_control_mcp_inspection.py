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


class _ServerRegistryStub:
    def list_all(self):
        return [
            SimpleNamespace(
                id="obsidian",
                title="Obsidian Vault",
                enabled=True,
                transport=SimpleNamespace(kind="http", endpoint="http://127.0.0.1:8765/mcp", command=""),
                policy=SimpleNamespace(trust_tier="partner", allow_resources=True, allow_tool_discovery=True),
            )
        ]


class _MCPServiceStub:
    def __init__(self):
        self.server_registry = _ServerRegistryStub()
        self.resource_catalog_by_server = {
            "obsidian": {
                "obsidian://note/a": SimpleNamespace(
                    uri="obsidian://note/a",
                    name="note-a",
                    title="Note A",
                    description="Atlas note",
                    mime_type="text/markdown",
                )
            }
        }
        self.last_refresh_stats = {
            "enabled": True,
            "registered_actions": 3,
            "servers_considered": 1,
            "servers_with_resources": 1,
        }

    def list_discovered_resources(self, server_id: str = ""):
        rows = [
            {
                "server_id": "obsidian",
                "uri": "obsidian://note/a",
                "name": "note-a",
                "title": "Note A",
                "description": "Atlas note",
                "mime_type": "text/markdown",
            }
        ]
        if server_id:
            return [row for row in rows if row["server_id"] == server_id]
        return rows


def _capability():
    kernel = SimpleNamespace(orchestrator=SimpleNamespace(mcp_integration_service=_MCPServiceStub()))
    return SystemCapability(kernel=kernel)


def test_system_control_mcp_status_returns_server_summary():
    capability = _capability()

    result = capability.execute("system.control.mcp.status", {}, {})

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["servers"][0]["id"] == "obsidian"
    assert result["servers"][0]["resource_count"] == 1
    assert result["refresh"]["servers_with_resources"] == 1


def test_system_control_mcp_resources_filters_rows():
    capability = _capability()

    result = capability.execute("system.control.mcp.resources", {"query": "atlas", "server_id": "obsidian"}, {})

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["items"][0]["uri"] == "obsidian://note/a"
    assert result["server_id"] == "obsidian"
