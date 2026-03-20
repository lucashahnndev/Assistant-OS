import asyncio

from src.capabilities.browser_control.playwright_mcp_adapter import PlaywrightMCPAdapter
from src.capabilities.browser_control.runtime_playwright import BrowserRuntimePlaywright


async def _fake_invoker(name, args):
    if name == "browser_navigate":
        return {"result": {"ok": True, "url": args.get("url")}}
    if name == "browser_run_code":
        code = str(args.get("code") or "")
        if "page.url" in code or "window.innerWidth" in code:
            return {"result": {"url": "https://example.com", "title": "Example", "viewport": {"w": 1280, "h": 720}}}
        if "window.scrollBy" in code:
            return {"result": {"delta_y": 600}}
        return {"result": {"ok": True}}
    if name == "browser_take_screenshot":
        path = str(args.get("filename") or "")
        if path:
            with open(path, "wb") as f:
                f.write(b"fake")
        return {"result": {"saved": True, "path": path}}
    if name == "browser_press_key":
        return {"result": {"ok": True}}
    if name == "browser_click":
        return {"result": {"ok": True}}
    if name == "browser_type":
        return {"result": {"ok": True}}
    raise RuntimeError(f"tool_not_found:{name}")


def test_playwright_mcp_adapter_basic_calls_via_invoker():
    adapter = PlaywrightMCPAdapter(endpoint="http://unused", invoker=_fake_invoker)

    info = asyncio.run(adapter.get_page_info())
    assert info["url"] == "https://example.com"
    assert info["viewport"]["w"] == 1280

    nav = asyncio.run(adapter.navigate("https://example.com"))
    assert isinstance(nav, dict)

    scr = asyncio.run(adapter.scroll_page(600))
    assert isinstance(scr, dict)

    raw = asyncio.run(adapter.capture_screenshot_bytes())
    assert raw == b"fake"


def test_runtime_playwright_launches_in_mcp_mode_when_endpoint_present():
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
        playwright_mcp_fallback_to_local=False,
    )
    asyncio.run(rt.launch())
    meta = rt.get_connection_metadata()
    assert meta["transport_mode_configured"] == "mcp"
    assert meta["transport_mode_effective"] == "mcp"


def test_runtime_playwright_mcp_without_endpoint_and_no_fallback_fails_fast():
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
        playwright_mcp_endpoint="",
        playwright_mcp_fallback_to_local=False,
    )
    try:
        asyncio.run(rt.launch())
        raised = False
    except RuntimeError:
        raised = True
    assert raised is True
