import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.server.main import create_app
from src.server.routes import system


class _ServerRegistryStub:
    def list_all(self):
        return [
            SimpleNamespace(
                id="obsidian",
                title="Obsidian Vault",
                enabled=True,
                transport=SimpleNamespace(kind="http", endpoint="http://127.0.0.1:8765/mcp", command="", startup_timeout_s=20),
                policy=SimpleNamespace(
                    trust_tier="partner",
                    namespace="mcp",
                    allow_tool_discovery=True,
                    allow_resources=True,
                    allow_prompts=False,
                    default_requires_approval=None,
                    tool_allowlist=["search_notes"],
                    tool_denylist=[],
                ),
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
            "registered_actions": 2,
            "servers_considered": 1,
            "servers_with_resources": 1,
        }
        self.refresh_calls = 0

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

    def refresh(self):
        self.refresh_calls += 1
        return dict(self.last_refresh_stats)


class _ConfigManagerStub:
    def get_data_dir(self):
        return tempfile.gettempdir()

    def get_interfaces_config(self):
        return {"server": {"cors_origins": ["http://localhost:5173"]}}


class _KernelStub:
    def __init__(self):
        self.config_manager = _ConfigManagerStub()
        self.orchestrator = SimpleNamespace(mcp_integration_service=_MCPServiceStub())


def _admin_user():
    return SimpleNamespace(role="admin")


def test_system_mcp_status_and_refresh_routes_expose_live_data():
    app = create_app(_KernelStub())
    app.dependency_overrides[system.get_current_user] = _admin_user
    client = TestClient(app)

    status = client.get("/api/system/mcp/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["enabled"] is True
    assert payload["servers"][0]["id"] == "obsidian"
    assert payload["resources"][0]["uri"] == "obsidian://note/a"

    refresh = client.post("/api/system/mcp/refresh")
    assert refresh.status_code == 200
    refresh_payload = refresh.json()
    assert refresh_payload["enabled"] is True
    assert refresh_payload["servers_with_resources"] == 1
