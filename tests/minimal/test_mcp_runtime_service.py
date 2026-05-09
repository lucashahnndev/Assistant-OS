import sys
import tempfile

from src.services.mcp_runtime_service import MCPRuntimeServiceManager


class _ProcStub:
    def __init__(self):
        self.pid = 4242
        self._terminated = False
        self.returncode = None

    def poll(self):
        if self._terminated:
            return 0
        return None

    def terminate(self):
        self._terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        _ = timeout
        self._terminated = True
        self.returncode = 0
        return 0


def test_mcp_runtime_service_autostart_local_server_process(monkeypatch):
    endpoint = "http://127.0.0.1:8787"
    cmd = f"{sys.executable} -m http.server 8787 --bind 127.0.0.1"
    with tempfile.TemporaryDirectory() as tmp:
        mgr = MCPRuntimeServiceManager(logs_dir=tmp)
        probe_calls = {"n": 0}

        def _fake_reachable(_endpoint: str, timeout_s: float = 0.4) -> bool:
            _ = timeout_s
            probe_calls["n"] += 1
            # First probe before spawn: down. Next probe after spawn: up.
            return probe_calls["n"] >= 2

        monkeypatch.setattr(
            "src.services.mcp_runtime_service.MCPRuntimeServiceManager._is_endpoint_reachable",
            staticmethod(_fake_reachable),
        )
        monkeypatch.setattr(
            "src.services.mcp_runtime_service.subprocess.Popen",
            lambda *args, **kwargs: _ProcStub(),
        )

        mgr.configure_from_browser_cfg(
            {
                "playwright_transport_mode": "mcp",
                "playwright_mcp_endpoint": endpoint,
                "playwright_mcp_autostart_enabled": True,
                "playwright_mcp_server_command": cmd,
                "playwright_mcp_startup_timeout_s": 8,
                "playwright_mcp_autorestart": True,
                "playwright_mcp_autostart_require_healthy": True,
            }
        )
        started = mgr.start()
        try:
            assert started.get("ok") is True
            health = mgr.ensure_running()
            assert health.get("ok") is True
        finally:
            _ = mgr.stop()


def test_mcp_runtime_service_fails_when_command_missing_for_local_endpoint():
    endpoint = "http://127.0.0.1:8787"
    with tempfile.TemporaryDirectory() as tmp:
        mgr = MCPRuntimeServiceManager(logs_dir=tmp)
        mgr.configure_from_browser_cfg(
            {
                "playwright_transport_mode": "mcp",
                "playwright_mcp_endpoint": endpoint,
                "playwright_mcp_autostart_enabled": True,
                "playwright_mcp_server_command": "",
                "playwright_mcp_startup_timeout_s": 5,
                "playwright_mcp_autorestart": True,
                "playwright_mcp_autostart_require_healthy": True,
            }
        )
        # Force the endpoint to be unreachable so the test remains deterministic.
        mgr._is_endpoint_reachable = staticmethod(lambda _endpoint, timeout_s=0.4: False)  # type: ignore[method-assign]
        out = mgr.start()
        assert out.get("ok") is False
        assert str(out.get("reason") or "") == "missing_server_command"


def test_mcp_runtime_service_preserves_existing_listener_when_takeover_requested(monkeypatch):
    endpoint = "http://127.0.0.1:8787"
    cmd = f"{sys.executable} -m http.server 8787 --bind 127.0.0.1"
    with tempfile.TemporaryDirectory() as tmp:
        mgr = MCPRuntimeServiceManager(logs_dir=tmp)
        state = {"reachable": True, "spawned": False, "takeover_calls": 0}

        def _fake_reachable(_endpoint: str, timeout_s: float = 0.4) -> bool:
            _ = (_endpoint, timeout_s)
            return bool(state["reachable"])

        def _fake_takeover(_self, _endpoint: str) -> bool:
            _ = (_self, _endpoint)
            state["takeover_calls"] += 1
            return False

        def _fake_popen(*args, **kwargs):
            _ = (args, kwargs)
            state["spawned"] = True
            state["reachable"] = True
            return _ProcStub()

        monkeypatch.setattr(
            "src.services.mcp_runtime_service.MCPRuntimeServiceManager._is_endpoint_reachable",
            staticmethod(_fake_reachable),
        )
        monkeypatch.setattr(
            "src.services.mcp_runtime_service.MCPRuntimeServiceManager._terminate_existing_listener",
            _fake_takeover,
        )
        monkeypatch.setattr(
            "src.services.mcp_runtime_service.subprocess.Popen",
            _fake_popen,
        )

        mgr.configure_from_browser_cfg(
            {
                "playwright_transport_mode": "mcp",
                "playwright_mcp_endpoint": endpoint,
                "playwright_mcp_autostart_enabled": True,
                "playwright_mcp_server_command": cmd,
                "playwright_mcp_takeover_existing": True,
            }
        )

        out = mgr.start()
        try:
            assert out.get("ok") is True
            assert out.get("managed") is False
            assert str(out.get("reason") or "") == "endpoint_already_reachable"
            assert state["takeover_calls"] == 0
            assert state["spawned"] is False
        finally:
            _ = mgr.stop()
