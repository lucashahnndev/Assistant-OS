import asyncio

from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability


class _KernelStub:
    config = {"agent": {"agent_name": "Test"}}

    class _Registry:
        def list_instances(self):
            return []

    browser_session_registry = _Registry()


class _RuntimeMetaStub:
    def get_connection_metadata(self):
        return {
            "backend": "playwright",
            "transport_mode_effective": "mcp",
            "mcp_calls_total": 9,
            "target_id": "mcp-target-1",
        }


def test_inspect_exposes_runtime_connection_metadata():
    cap = BrowserControlCapability(_KernelStub(), {"runtime_backend": "playwright"})
    cap._runtime = _RuntimeMetaStub()

    out = asyncio.run(cap.inspect(params={}, context={}))
    assert out["ok"] is True
    current = out.get("current_execution") or {}
    conn = current.get("runtime_connection") or {}
    assert conn.get("transport_mode_effective") == "mcp"
    assert conn.get("mcp_calls_total") == 9


def test_health_reports_missing_runtime_target_issue_when_sync_has_none():
    cap = BrowserControlCapability(_KernelStub(), {"runtime_backend": "playwright"})

    async def _fake_inspect(params=None, context=None):
        return {
            "ok": True,
            "instances": [],
            "count": 0,
            "current_execution": {
                "browser_instance_id": "inst-1",
                "tab_id": "tab-1",
                "owner_session_id": "session-1",
                "runtime_backend": "playwright",
                "runtime_connection": {},
            },
        }

    async def _fake_sync_registry(context=None):
        return {
            "ok": True,
            "runtime_backend": "playwright",
            "runtime_target_id": "",
            "cdp_target_id": "",
            "mcp_calls_total": 0,
        }

    cap.inspect = _fake_inspect  # type: ignore[method-assign]
    cap.sync_registry = _fake_sync_registry  # type: ignore[method-assign]

    out = asyncio.run(cap.health(params={"run_gc": False}, context={}))
    assert out["ok"] is True
    issues = (out.get("health") or {}).get("issues") or []
    assert "no_active_runtime_target" in issues


def test_health_reports_mcp_transport_not_effective_and_missing_endpoint_signals():
    cap = BrowserControlCapability(_KernelStub(), {"runtime_backend": "playwright"})

    async def _fake_inspect(params=None, context=None):
        return {
            "ok": True,
            "instances": [],
            "count": 0,
            "current_execution": {
                "browser_instance_id": "inst-1",
                "tab_id": "tab-1",
                "owner_session_id": "session-1",
                "runtime_backend": "playwright",
                "runtime_connection": {},
            },
        }

    async def _fake_sync_registry(context=None):
        return {
            "ok": True,
            "runtime_backend": "playwright",
            "transport_mode_configured": "mcp",
            "transport_mode_effective": "local",
            "mcp_endpoint": "",
            "runtime_target_id": "target-1",
            "cdp_target_id": "target-1",
            "mcp_calls_total": 0,
        }

    cap.inspect = _fake_inspect  # type: ignore[method-assign]
    cap.sync_registry = _fake_sync_registry  # type: ignore[method-assign]

    out = asyncio.run(cap.health(params={"run_gc": False}, context={}))
    assert out["ok"] is True
    issues = (out.get("health") or {}).get("issues") or []
    assert "mcp_transport_not_effective" in issues
    assert "mcp_mode_without_endpoint" in issues


def test_health_does_not_run_gc_even_when_requested():
    cap = BrowserControlCapability(_KernelStub(), {"runtime_backend": "playwright"})
    called = {"gc": 0}

    async def _fake_inspect(params=None, context=None):
        return {
            "ok": True,
            "instances": [],
            "count": 0,
            "current_execution": {
                "browser_instance_id": "inst-1",
                "tab_id": "tab-1",
                "owner_session_id": "session-1",
                "runtime_backend": "playwright",
                "runtime_connection": {},
            },
        }

    async def _fake_sync_registry(context=None):
        return {
            "ok": True,
            "runtime_backend": "playwright",
            "transport_mode_configured": "mcp",
            "transport_mode_effective": "mcp",
            "mcp_endpoint": "http://127.0.0.1:8787",
            "runtime_target_id": "target-1",
            "cdp_target_id": "target-1",
            "mcp_calls_total": 0,
        }

    async def _fake_gc(params=None, context=None):
        called["gc"] += 1
        return {"ok": True, "gc": {"closed_idle": {"closed_instances": 99}}}

    cap.inspect = _fake_inspect  # type: ignore[method-assign]
    cap.sync_registry = _fake_sync_registry  # type: ignore[method-assign]
    cap.gc = _fake_gc  # type: ignore[method-assign]

    out = asyncio.run(cap.health(params={"run_gc": True, "gc_params": {"idle_seconds": 1}}, context={}))
    assert out["ok"] is True
    assert called["gc"] == 0
    gc_block = out.get("gc") or {}
    assert gc_block.get("reason") == "health_does_not_run_gc"
