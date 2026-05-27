import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.capabilities.browser_control.playwright_mcp_adapter import PlaywrightMCPAdapter
from src.capabilities.browser_control.runtime_playwright import BrowserRuntimePlaywright

_FAKE_TAB_STATE = {"tabs": [{"index": 0, "title": "Tab 0"}], "active_index": 0}


async def _fake_invoker(name, args):
    if name == "browser_tabs":
        action = str(args.get("action") or "").strip().lower()
        if action == "list":
            return {"result": {"tabs": list(_FAKE_TAB_STATE["tabs"]), "active_index": int(_FAKE_TAB_STATE["active_index"])}}
        if action == "new":
            idx = len(_FAKE_TAB_STATE["tabs"])
            _FAKE_TAB_STATE["tabs"].append({"index": idx, "title": f"Tab {idx}"})
            _FAKE_TAB_STATE["active_index"] = idx
            return {"result": {"index": idx}}
        if action == "create":
            idx = len(_FAKE_TAB_STATE["tabs"])
            _FAKE_TAB_STATE["tabs"].append({"index": idx, "title": f"Tab {idx}"})
            _FAKE_TAB_STATE["active_index"] = idx
            return {"result": {"index": idx}}
        if action == "select":
            idx = int(args.get("index", 0) or 0)
            _FAKE_TAB_STATE["active_index"] = idx
            return {"result": {"ok": True, "index": idx}}
        return {"result": {"ok": True}}
    if name == "browser_navigate":
        return {"result": {"ok": True, "url": args.get("url")}}
    if name == "browser_run_code":
        code = str(args.get("code") or "")
        if "fallback_clicked" in code and "elementFromPoint" in code:
            return {
                "result": {
                    "clicked": True,
                    "fallback_clicked": True,
                    "hit_after": {
                        "top_tag": "span",
                        "top_text": "Sort by",
                        "has_interactive_ancestor": True,
                        "interactive_tag": "button",
                    },
                }
            }
        if "querySelectorAll" in code and "total_count" in code:
            return {
                "result": {
                    "nodes": [
                        {
                            "id": "pw_node_0",
                            "tag": "button",
                            "role": "button",
                            "text": "Sort by",
                            "inViewport": True,
                            "bbox": {"x": 10, "y": 20, "w": 100, "h": 30},
                        }
                    ],
                    "markers": [{"id": "mk_1", "kind": "heading", "text": "Results"}],
                    "focus": {"tag": "input", "id": "twotabsearchtextbox", "role": "searchbox"},
                    "total_count": 1,
                    "viewport_count": 1,
                }
            }
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
    _FAKE_TAB_STATE["tabs"] = [{"index": 0, "title": "Tab 0"}]
    _FAKE_TAB_STATE["active_index"] = 0
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
    dom = asyncio.run(adapter.get_skeletal_dom())
    assert dom["total_count"] == 1
    assert len(dom["nodes"]) == 1
    assert dom["nodes"][0]["id"] == "pw_node_0"
    assert dom["markers"][0]["id"] == "mk_1"
    assert adapter.calls_total >= 4


def test_playwright_mcp_adapter_tab_lifecycle_via_invoker():
    _FAKE_TAB_STATE["tabs"] = [{"index": 0, "title": "Tab 0"}]
    _FAKE_TAB_STATE["active_index"] = 0
    adapter = PlaywrightMCPAdapter(endpoint="http://unused", invoker=_fake_invoker)

    listed = asyncio.run(adapter.list_tabs())
    assert listed["active_index"] == 0
    assert len(listed["tabs"]) == 1

    created = asyncio.run(adapter.create_tab("https://example.com"))
    assert created["index"] == 1
    listed2 = asyncio.run(adapter.list_tabs())
    assert listed2["active_index"] == 1
    assert len(listed2["tabs"]) == 2

    _ = asyncio.run(adapter.select_tab(0))
    listed3 = asyncio.run(adapter.list_tabs())
    assert listed3["active_index"] == 0


def test_playwright_mcp_adapter_create_tab_prefers_browser_tabs_new():
    calls = []

    async def _invoker(name, args):
        calls.append({"name": name, "args": dict(args or {})})
        if name == "browser_tabs":
            action = str(args.get("action") or "").strip().lower()
            if action == "new":
                return {"result": {"index": 2}}
            if action == "list":
                return {"result": {"tabs": [{"index": 0}, {"index": 1}, {"index": 2}], "active_index": 2}}
        raise RuntimeError(f"unexpected_call:{name}")

    adapter = PlaywrightMCPAdapter(endpoint="http://unused", invoker=_invoker)
    created = asyncio.run(adapter.create_tab("https://example.com"))

    assert created["index"] == 2
    assert calls[0]["name"] == "browser_tabs"
    assert calls[0]["args"]["action"] == "new"
    assert calls[0]["args"]["url"] == "https://example.com"


def test_runtime_playwright_launches_in_mcp_mode_when_endpoint_present():
    _FAKE_TAB_STATE["tabs"] = [{"index": 0, "title": "Tab 0"}]
    _FAKE_TAB_STATE["active_index"] = 0
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
    with patch(
        "src.capabilities.browser_control.runtime_playwright.PlaywrightMCPAdapter",
        side_effect=lambda endpoint, **kwargs: PlaywrightMCPAdapter(endpoint="http://unused", invoker=_fake_invoker, **kwargs),
    ):
        asyncio.run(rt.launch())
    meta = rt.get_connection_metadata()
    assert meta["transport_mode_configured"] == "mcp"
    assert meta["transport_mode_effective"] == "mcp"
    assert int(meta["mcp_calls_total"]) >= 1
    assert meta["target_id"] == "mcp_tab_0"
    assert meta["mcp_tab_index"] == 0


def test_runtime_playwright_mcp_open_new_tab_and_attach_target():
    _FAKE_TAB_STATE["tabs"] = [{"index": 0, "title": "Tab 0"}]
    _FAKE_TAB_STATE["active_index"] = 0
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
    with patch(
        "src.capabilities.browser_control.runtime_playwright.PlaywrightMCPAdapter",
        side_effect=lambda endpoint, **kwargs: PlaywrightMCPAdapter(endpoint="http://unused", invoker=_fake_invoker, **kwargs),
    ):
        asyncio.run(rt.launch())
        target = asyncio.run(rt.open_new_tab("https://example.com"))
        assert target == "mcp_tab_1"
        attached = asyncio.run(rt.attach_to_target("mcp_tab_0"))
        assert attached is True
        assert rt.target_id == "mcp_tab_0"


def test_runtime_playwright_mcp_click_receipt_exposes_fallback_clicked():
    _FAKE_TAB_STATE["tabs"] = [{"index": 0, "title": "Tab 0"}]
    _FAKE_TAB_STATE["active_index"] = 0
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
    with patch(
        "src.capabilities.browser_control.runtime_playwright.PlaywrightMCPAdapter",
        side_effect=lambda endpoint, **kwargs: PlaywrightMCPAdapter(endpoint="http://unused", invoker=_fake_invoker, **kwargs),
    ):
        asyncio.run(rt.launch())
        resp = asyncio.run(rt.click(x=780, y=170))
    data = resp.result_data if isinstance(resp.result_data, dict) else {}
    assert data.get("fallback_clicked") is True


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


def test_playwright_mcp_adapter_uses_mcp_jsonrpc_endpoint():
    calls = []

    class _Resp:
        def __init__(self, status_code=200, data=None, headers=None):
            self.status_code = status_code
            self._data = data if data is not None else {}
            self.headers = headers if headers is not None else {}
            self.text = json.dumps(self._data)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http_status_{self.status_code}")

        def json(self):
            return self._data

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append({"url": str(url), "json": dict(json or {}), "headers": dict(headers or {})})
            method = str((json or {}).get("method", "")).strip()
            if method == "initialize":
                return _Resp(
                    status_code=200,
                    data={"jsonrpc": "2.0", "id": (json or {}).get("id"), "result": {"capabilities": {}}},
                    headers={"mcp-session-id": "sess_123"},
                )
            if method == "notifications/initialized":
                return _Resp(status_code=200, data={})
            if method == "tools/call":
                return _Resp(
                    status_code=200,
                    data={
                        "jsonrpc": "2.0",
                        "id": (json or {}).get("id"),
                        "result": {"tabs": [{"index": 0}], "active_index": 0},
                    },
                )
            return _Resp(status_code=400, data={"error": {"message": "unexpected_method"}})

    adapter = PlaywrightMCPAdapter(endpoint="http://127.0.0.1:8787")
    with patch("src.capabilities.browser_control.playwright_mcp_adapter.httpx.AsyncClient", return_value=_Client()):
        listed = asyncio.run(adapter.list_tabs())

    assert listed["active_index"] == 0
    assert len(listed["tabs"]) == 1
    assert any(c["url"].startswith("http://localhost:8787/") and c["url"].endswith("/mcp") for c in calls)
    assert any(c["json"].get("method") == "initialize" for c in calls)
    assert any(c["json"].get("method") == "tools/call" for c in calls)


def test_playwright_mcp_adapter_supports_explicit_legacy_tools_call_endpoint():
    calls = []

    class _Resp:
        def __init__(self, status_code=200, data=None):
            self.status_code = status_code
            self._data = data if data is not None else {}
            self.headers = {}
            self.text = json.dumps(self._data)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http_status_{self.status_code}")

        def json(self):
            return self._data

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append({"url": str(url), "json": dict(json or {})})
            return _Resp(status_code=200, data={"result": {"ok": True}})

    adapter = PlaywrightMCPAdapter(endpoint="http://127.0.0.1:8787/tools/call")
    with patch("src.capabilities.browser_control.playwright_mcp_adapter.httpx.AsyncClient", return_value=_Client()):
        out = asyncio.run(adapter.navigate("https://example.com"))
    assert isinstance(out, dict)
    assert any(c["url"].endswith("/tools/call") for c in calls)


def test_playwright_mcp_adapter_decodes_sse_payloads():
    calls = []

    class _Resp:
        def __init__(self, status_code=200, text="", headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers if headers is not None else {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http_status_{self.status_code}")

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append({"url": str(url), "json": dict(json or {}), "headers": dict(headers or {})})
            method = str((json or {}).get("method", "")).strip()
            if method == "initialize":
                return _Resp(
                    status_code=200,
                    text=(
                        "event: message\n"
                        'data: {"jsonrpc":"2.0","id":1,"result":{"capabilities":{"tools":{}}}}\n'
                    ),
                    headers={"mcp-session-id": "sess_sse"},
                )
            if method == "notifications/initialized":
                return _Resp(status_code=200, text='{"jsonrpc":"2.0","result":{}}')
            if method == "tools/call":
                return _Resp(
                    status_code=200,
                    text=(
                        "event: message\n"
                        'data: {"jsonrpc":"2.0","id":2,"result":{"tabs":[{"index":0}],"active_index":0}}\n'
                    ),
                )
            return _Resp(status_code=400, text='{"error":{"message":"unexpected_method"}}')

    adapter = PlaywrightMCPAdapter(endpoint="http://localhost:8787")
    with patch("src.capabilities.browser_control.playwright_mcp_adapter.httpx.AsyncClient", return_value=_Client()):
        listed = asyncio.run(adapter.list_tabs())

    assert listed["active_index"] == 0
    assert len(listed["tabs"]) == 1
    assert any(c["json"].get("method") == "initialize" for c in calls)
    assert any(c["json"].get("method") == "tools/call" for c in calls)


def test_playwright_mcp_adapter_does_not_fallback_to_tools_call_when_mcp_404():
    calls = []

    class _Resp:
        def __init__(self, status_code=200, text="", headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers if headers is not None else {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http_status_{self.status_code}")

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            url_s = str(url)
            calls.append({"url": url_s, "json": dict(json or {}), "headers": dict(headers or {})})
            method = str((json or {}).get("method", "")).strip()
            if url_s.endswith("/mcp"):
                return _Resp(status_code=404, text="Not Found")
            return _Resp(status_code=400, text='{"error":{"message":"unexpected"}}')

    adapter = PlaywrightMCPAdapter(endpoint="http://localhost:8787")
    with patch("src.capabilities.browser_control.playwright_mcp_adapter.httpx.AsyncClient", return_value=_Client()):
        raised = None
        try:
            _ = asyncio.run(adapter.list_tabs())
        except Exception as e:
            raised = e

    assert raised is not None
    assert any(c["url"].endswith("/mcp") for c in calls)
    assert not any(c["url"].endswith("/tools/call") for c in calls)


def test_playwright_mcp_adapter_reinitializes_and_retries_on_404_session_loss():
    calls = []
    state = {"tool_calls": 0, "init_calls": 0}

    class _Resp:
        def __init__(self, status_code=200, text="", headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers if headers is not None else {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http_status_{self.status_code}")

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append({"url": str(url), "json": dict(json or {}), "headers": dict(headers or {})})
            method = str((json or {}).get("method", "")).strip()
            if method == "initialize":
                state["init_calls"] += 1
                sid = f"sess_{state['init_calls']}"
                return _Resp(
                    status_code=200,
                    text='event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"capabilities":{"tools":{}}}}\n',
                    headers={"mcp-session-id": sid},
                )
            if method == "notifications/initialized":
                return _Resp(status_code=202, text="")
            if method == "tools/call":
                state["tool_calls"] += 1
                if state["tool_calls"] == 1:
                    return _Resp(status_code=404, text='{"error":{"message":"session_not_found"}}')
                return _Resp(
                    status_code=200,
                    text='event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"tabs":[{"index":0}],"active_index":0}}\n',
                )
            return _Resp(status_code=400, text='{"error":{"message":"unexpected"}}')

    adapter = PlaywrightMCPAdapter(endpoint="http://localhost:8787")
    with patch("src.capabilities.browser_control.playwright_mcp_adapter.httpx.AsyncClient", return_value=_Client()):
        listed = asyncio.run(adapter.list_tabs())

    assert listed["active_index"] == 0
    assert len(listed["tabs"]) == 1
    assert state["init_calls"] >= 2
    assert state["tool_calls"] == 2


def test_playwright_mcp_adapter_parses_json_from_content_text():
    payload = {
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "### Result\n"
                        '{"url":"https://example.com","title":"Example Domain","viewport":{"w":1280,"h":720}}\n'
                        "### Ran Playwright code"
                    ),
                }
            ]
        }
    }
    out = PlaywrightMCPAdapter._coerce_result_payload(payload)
    assert out.get("url") == "https://example.com"
    assert out.get("title") == "Example Domain"
    assert isinstance(out.get("viewport"), dict)


def test_playwright_mcp_adapter_parses_tabs_from_content_text():
    payload = {
        "content": [
            {
                "type": "text",
                "text": (
                    "### Result\n"
                    "- 0: (current) [Example](https://example.com)\n"
                    "- 1: [Amazon](https://www.amazon.com.br)\n"
                ),
            }
        ]
    }
    tabs = PlaywrightMCPAdapter._coerce_tabs_payload(payload)
    assert len(tabs) == 2
    assert tabs[0]["index"] == 0
    assert tabs[0]["current"] is True
    assert "example.com" in tabs[0]["url"]


def test_runtime_playwright_mcp_navigate_retries_when_info_stays_blank():
    class _FlakyAdapter:
        def __init__(self):
            self.navigate_calls = []
            self.info_calls = 0

        async def list_tabs(self):
            return {"tabs": [{"index": 0, "title": "Tab 0"}], "active_index": 0}

        async def get_page_info(self):
            self.info_calls += 1
            if self.info_calls < 3:
                return {"url": "about:blank", "title": "", "viewport": {"w": 1280, "h": 720}}
            return {"url": "https://example.com/", "title": "Example Domain", "viewport": {"w": 1280, "h": 720}}

        async def navigate(self, url):
            self.navigate_calls.append(str(url))
            return {"result": {"ok": True}}

    flaky = _FlakyAdapter()
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
    with patch(
        "src.capabilities.browser_control.runtime_playwright.PlaywrightMCPAdapter",
        side_effect=lambda endpoint, **kwargs: flaky,
    ):
        asyncio.run(rt.launch())
        resp = asyncio.run(rt.navigate("https://example.com"))

    assert resp.status == "success"
    assert len(flaky.navigate_calls) == 2
    assert all(u == "https://example.com" for u in flaky.navigate_calls)
    assert isinstance(resp.result_data, dict)
    assert "recovered_after_blank" in resp.result_data
