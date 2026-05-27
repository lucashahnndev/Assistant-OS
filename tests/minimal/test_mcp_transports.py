import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.services.mcp.models import MCPServerConfig
from src.services.mcp.transports import MCPHTTPTransportClient, MCPStdioTransportClient


class _ResponseStub:
    def __init__(self, payload, status_code=200, headers=None):
        self.text = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _SessionStub:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "json": dict(json or {}),
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        method = str((json or {}).get("method") or "")
        if method == "initialize":
            return _ResponseStub('{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}}', headers={"mcp-session-id": "s-123"})
        if method == "notifications/initialized":
            return _ResponseStub("{}")
        if method == "tools/list":
            return _ResponseStub(
                '{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"search_notes","description":"Search notes","inputSchema":{"type":"object","properties":{"query":{"type":"string"}}},"annotations":{"readOnlyHint":true}}]}}'
            )
        if method == "tools/call":
            return _ResponseStub('{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"ok"}]}}')
        if method == "resources/list":
            return _ResponseStub(
                '{"jsonrpc":"2.0","id":4,"result":{"resources":[{"uri":"obsidian://note/a","name":"note-a","title":"Note A","mimeType":"text/markdown"}]}}'
            )
        if method == "resources/read":
            return _ResponseStub('{"jsonrpc":"2.0","id":5,"result":{"contents":[{"uri":"obsidian://note/a","mimeType":"text/markdown","text":"hello atlas"}]}}')
        raise AssertionError(f"unexpected method {method}")

    def close(self):
        return None


class _ProcStub:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(
            "\n".join(
                [
                    '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25"}}',
                    '{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"read_note","annotations":{"readOnlyHint":true}}]}}',
                    '{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"done"}]}}',
                    '{"jsonrpc":"2.0","id":4,"result":{"resources":[{"uri":"obsidian://note/a","title":"Note A","mimeType":"text/markdown"}]}}',
                    '{"jsonrpc":"2.0","id":5,"result":{"contents":[{"uri":"obsidian://note/a","mimeType":"text/markdown","text":"hello atlas"}]}}',
                ]
            )
            + "\n"
        )
        self.stderr = io.StringIO("")
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        _ = timeout
        return 0

    def kill(self):
        self.terminated = True


def _http_server():
    return MCPServerConfig.model_validate(
        {
            "id": "obsidian",
            "title": "Obsidian",
            "transport": {
                "kind": "http",
                "endpoint": "http://127.0.0.1:8765",
                "startup_timeout_s": 5,
            },
        }
    )


def _stdio_server():
    return MCPServerConfig.model_validate(
        {
            "id": "obsidian",
            "title": "Obsidian",
            "transport": {
                "kind": "stdio",
                "command": "obsidian-mcp",
                "startup_timeout_s": 5,
            },
        }
    )


def test_http_transport_initializes_lists_tools_and_invokes(monkeypatch):
    session = _SessionStub()
    monkeypatch.setattr("src.services.mcp.transports.requests.Session", lambda: session)
    client = MCPHTTPTransportClient(_http_server())

    tools = client.list_tools()
    result = client.invoke_tool("search_notes", {"query": "atlas"})
    resources = client.list_resources()
    resource_payload = client.read_resource("obsidian://note/a")

    assert [tool.name for tool in tools] == ["search_notes"]
    assert [resource.uri for resource in resources] == ["obsidian://note/a"]
    assert result["content"][0]["text"] == "ok"
    assert resource_payload["contents"][0]["text"] == "hello atlas"
    assert session.calls[0]["url"] == "http://localhost:8765/mcp"
    assert session.calls[2]["json"]["method"] == "tools/list"
    assert session.calls[3]["headers"]["mcp-session-id"] == "s-123"
    assert session.calls[4]["json"]["method"] == "resources/list"
    assert session.calls[5]["json"]["method"] == "resources/read"


def test_stdio_transport_initializes_lists_tools_and_invokes(monkeypatch):
    proc = _ProcStub()
    monkeypatch.setattr("src.services.mcp.transports.subprocess.Popen", lambda *args, **kwargs: proc)
    client = MCPStdioTransportClient(_stdio_server())

    tools = client.list_tools()
    result = client.invoke_tool("read_note", {"path": "x.md"})
    resources = client.list_resources()
    resource_payload = client.read_resource("obsidian://note/a")
    stdin_text = proc.stdin.getvalue()
    client.close()

    assert [tool.name for tool in tools] == ["read_note"]
    assert [resource.uri for resource in resources] == ["obsidian://note/a"]
    assert result["content"][0]["text"] == "done"
    assert resource_payload["contents"][0]["text"] == "hello atlas"
    assert '"method":"initialize"' in stdin_text
    assert '"method":"tools/list"' in stdin_text
    assert '"method":"tools/call"' in stdin_text
    assert '"method":"resources/list"' in stdin_text
    assert '"method":"resources/read"' in stdin_text
    assert proc.terminated is True
