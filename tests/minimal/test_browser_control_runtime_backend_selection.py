from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability


class _KernelStub:
    config = {"agent": {"agent_name": "Test"}}


def test_runtime_backend_defaults_to_cdp_on_invalid_config():
    cap = BrowserControlCapability(_KernelStub(), {"runtime_backend": "invalid_backend"})
    assert cap._resolve_runtime_backend() == "cdp"


def test_runtime_backend_supports_playwright_and_cdp_runtime_class_resolution():
    cap_cdp = BrowserControlCapability(_KernelStub(), {"runtime_backend": "cdp"})
    cls_cdp = cap_cdp._resolve_runtime_class()
    assert cls_cdp.__name__ == "BrowserRuntime"

    cap_pw = BrowserControlCapability(_KernelStub(), {"runtime_backend": "playwright"})
    cls_pw = cap_pw._resolve_runtime_class()
    assert cls_pw.__name__ == "BrowserRuntimePlaywright"
