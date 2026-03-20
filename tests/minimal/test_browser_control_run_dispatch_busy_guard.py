from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability


class _KernelStub:
    config = {"agent": {"agent_name": "Test"}}


def test_browser_run_dispatch_busy_guard_blocks_parallel_entry():
    cap = BrowserControlCapability(_KernelStub(), {})
    acquired = cap._run_dispatch_lock.acquire(blocking=False)
    assert acquired is True
    try:
        out = cap.execute(
            "browser.control.run",
            {"goal": "abrir https://example.com", "intent_class": "realizar_pesquisa"},
            {},
        )
        assert out.get("ok") is False
        assert out.get("error_code") == "BROWSER_RUN_DISPATCH_BUSY"
    finally:
        cap._run_dispatch_lock.release()
