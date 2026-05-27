import json
import subprocess
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

import scripts.obsidian_mcp_preflight as preflight


def _run_cli(args):
    cmd = [
        str(ROOT / "env" / "bin" / "python"),
        str(ROOT / "scripts" / "obsidian_mcp_preflight.py"),
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=False)


def test_analyze_obsidian_mcp_readiness_detects_missing_server():
    out = preflight.analyze_obsidian_mcp_readiness({"enabled": True, "servers": []})
    assert out["ready"] is False
    assert "obsidian_server_missing" in out["issues"]


def test_analyze_obsidian_mcp_readiness_accepts_http_server():
    out = preflight.analyze_obsidian_mcp_readiness(
        {
            "enabled": True,
            "servers": [
                {
                    "id": "obsidian",
                    "title": "Obsidian Vault",
                    "enabled": True,
                    "transport": {"kind": "http", "endpoint": "http://127.0.0.1:8765/mcp"},
                    "policy": {"allow_tool_discovery": True, "allow_resources": True},
                }
            ],
        }
    )
    assert out["ready"] is True
    assert out["issues"] == []


def test_cli_check_config_reports_not_ready_when_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.json"
        cfg_path.write_text(json.dumps({"mcp": {"enabled": False, "servers": []}}), encoding="utf-8")
        out = _run_cli(["--config-file", str(cfg_path), "check-config"])
        assert out.returncode == 0
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is True
        assert payload["obsidian_mcp"]["ready"] is False
        assert "mcp_disabled" in payload["obsidian_mcp"]["issues"]


def test_cli_check_config_require_ready_fails_when_not_ready():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.json"
        cfg_path.write_text(json.dumps({"mcp": {"enabled": False, "servers": []}}), encoding="utf-8")
        out = _run_cli(["--config-file", str(cfg_path), "check-config", "--require-ready"])
        assert out.returncode == 2
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is False
        assert payload["error_code"] == "OBSIDIAN_MCP_NOT_READY"


def test_probe_server_success_with_mocked_client_manager(monkeypatch):
    class _Tool:
        def __init__(self, name):
            self.name = name

    class _Resource:
        def __init__(self, uri):
            self.uri = uri

    class _FakeManager:
        def list_tools(self, server):
            assert server.id == "obsidian"
            return [_Tool("search_notes"), _Tool("read_note")]

        def list_resources(self, server):
            assert server.id == "obsidian"
            return [_Resource("obsidian://note/a")]

        def close_all(self):
            return None

    monkeypatch.setattr(preflight, "MCPClientManager", lambda: _FakeManager())
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "mcp": {
                        "enabled": True,
                        "servers": [
                            {
                                "id": "obsidian",
                                "title": "Obsidian Vault",
                                "enabled": True,
                                "transport": {"kind": "http", "endpoint": "http://127.0.0.1:8765/mcp"},
                                "policy": {"allow_tool_discovery": True, "allow_resources": True},
                            }
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )
        out = preflight.cmd_probe_server(Namespace(config_file=str(cfg_path), server_id="obsidian"))
        assert out["ok"] is True
        assert out["tool_count"] == 2
        assert out["resource_count"] == 1
        assert "search_notes" in out["tools"]
        assert "obsidian://note/a" in out["resources"]


def test_discover_vaults_returns_structured_payload(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "discover_obsidian_vaults",
        lambda: [{"vault_id": "v1", "path": "/tmp/vault", "open": True, "ts": 1, "source": "/tmp/obsidian.json"}],
    )
    out = preflight.cmd_discover_vaults(Namespace())
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["vaults"][0]["path"] == "/tmp/vault"
