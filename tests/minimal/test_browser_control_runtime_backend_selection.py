from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability
from src.capabilities.browser_control.runtime_playwright import BrowserRuntimePlaywright


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


def test_playwright_transport_mode_defaults_and_fallback_behavior():
    rt = BrowserRuntimePlaywright(
        chrome_path="",
        base_profile_path="data/browser_data/profile",
        overlay_profile_parent="data/browser_data/profile/sessions",
        desktop_cache_dir="data/browser_data/desktop_cache",
        desktop_launch_enabled=False,
        extension_install_mode="auto",
        extension_fallback_enabled=True,
        headless=True,
        muted=True,
        app_mode=False,
        launch_url="about:blank",
        humanize_input_enabled=True,
        visual_cursor_enabled=True,
        tab_user_lock_enabled=True,
        tab_control_bar_enabled=True,
        agent_name="Test",
        playwright_transport_mode="mcp",
        playwright_mcp_endpoint="http://localhost:8787",
        playwright_mcp_fallback_to_local=True,
    )
    assert rt._resolve_transport_mode() == "mcp"
    meta = rt.get_connection_metadata()
    assert meta["transport_mode_configured"] == "mcp"
    assert meta["mcp_fallback_to_local"] is True
