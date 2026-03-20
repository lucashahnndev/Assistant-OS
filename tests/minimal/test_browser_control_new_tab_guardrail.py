import asyncio
import tempfile

from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability


class _KernelStub:
    config = {"agent": {"agent_name": "Test"}}


class _RuntimeStub:
    def __init__(self):
        self.new_tab_calls = 0
        self.navigate_calls = 0

    async def _get_current_url(self):
        return "https://example.com"

    async def open_new_tab(self, _url: str):
        self.new_tab_calls += 1
        return f"target-{self.new_tab_calls}"

    async def navigate(self, _url: str):
        self.navigate_calls += 1
        return {"ok": True}


def test_apply_session_policy_blocks_new_tab_after_session_budget():
    with tempfile.TemporaryDirectory() as _tmp:
        capability = BrowserControlCapability(_KernelStub(), {"max_new_tabs_per_session": 1})
        runtime = _RuntimeStub()
        capability._runtime = runtime
        capability._owner_session_id = "sess-guard"
        capability._runtime_intent_class = "realizar_pesquisa"

        async def _noop_ensure_runtime(**kwargs):
            _ = kwargs
            return None

        capability._ensure_runtime = _noop_ensure_runtime  # type: ignore[method-assign]

        first = asyncio.run(
            capability._apply_session_policy(
                goal="abrir https://github.com",
                user_request="abrir https://github.com",
                intent_class="realizar_pesquisa",
                owner_session_id="sess-guard",
                headless=True,
                muted=True,
            )
        )
        assert first.get("route") == "new_tab"
        assert first.get("new_tab_opened") is True
        assert first.get("new_tab_opened_count") == 1
        assert runtime.new_tab_calls == 1

        second = asyncio.run(
            capability._apply_session_policy(
                goal="abrir https://google.com",
                user_request="abrir https://google.com",
                intent_class="realizar_pesquisa",
                owner_session_id="sess-guard",
                headless=True,
                muted=True,
            )
        )
        assert second.get("route") == "reuse_tab"
        assert second.get("new_tab_blocked") == "max_new_tabs_per_session_exceeded"
        assert second.get("fallback_navigation") == "reuse_tab_navigate"
        assert runtime.new_tab_calls == 1
        assert runtime.navigate_calls == 1
