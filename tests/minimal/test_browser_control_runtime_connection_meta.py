from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability


class _KernelStub:
    config = {"agent": {"agent_name": "Test"}}


class _RuntimeStub:
    def get_connection_metadata(self):
        return {
            "backend": "playwright",
            "transport_mode_effective": "mcp",
            "mcp_calls_total": 42,
            "target_id": "runtime-target-1",
        }


def test_runtime_connection_meta_helper_reads_runtime_metadata():
    cap = BrowserControlCapability(_KernelStub(), {})
    cap._runtime = _RuntimeStub()

    meta = cap._runtime_connection_meta()
    assert meta.get("backend") == "playwright"
    assert meta.get("mcp_calls_total") == 42

    target = cap._current_target_id()
    assert target == "runtime-target-1"
