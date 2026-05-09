import asyncio
import tempfile

from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability


class _KernelStub:
    config = {"agent": {"agent_name": "Test"}}


class _RuntimeStub:
    remote_debugging_port = 9555
    target_id = "target-1"

    def get_connection_metadata(self):
        return {
            "debug_port": self.remote_debugging_port,
            "target_id": self.target_id,
            "ws_url": "ws://localhost:9555/devtools/page/target-1",
            "app_mode": False,
            "launch_url": "https://example.com",
        }

    async def _get_current_url(self):
        return "https://example.com"

    async def _get_current_title(self):
        return "Example"

    async def attach_to_target(self, target_id: str):
        self.target_id = target_id
        return True


class _SubagentStub:
    async def run_to_goal(self, *args, **kwargs):
        _ = (args, kwargs)
        class _Resp:
            def model_dump(self, mode="json"):
                _ = mode
                return {"status": "success"}
        return _Resp()


def test_run_goal_does_not_auto_close_or_gc():
    with tempfile.TemporaryDirectory() as tmp:
        cap = BrowserControlCapability(_KernelStub(), {"registry_gc_enabled": True})
        cap._runtime = _RuntimeStub()
        cap._subagent = _SubagentStub()
        cap._owner_session_id = "sess-1"
        cap._runtime_intent_class = "realizar_pesquisa"

        async def _fake_apply_session_policy(**kwargs):
            _ = kwargs
            return {
                "route": "reuse_tab",
                "reason": "same_session_reuse",
                "use_app_mode": False,
                "force_new_instance": False,
                "launch_url": "https://example.com",
            }

        async def _fail_if_called(*args, **kwargs):
            _ = (args, kwargs)
            raise AssertionError("automatic close/gc should not be triggered")

        async def _noop_ensure_runtime(**kwargs):
            _ = kwargs
            return None

        cap._apply_session_policy = _fake_apply_session_policy  # type: ignore[method-assign]
        cap._close_registered_instance = _fail_if_called  # type: ignore[method-assign]
        cap._maybe_run_registry_gc = _fail_if_called  # type: ignore[method-assign]
        cap._ensure_runtime = _noop_ensure_runtime  # type: ignore[method-assign]
        cap._is_browser_launch_authorized = lambda _ctx: True  # type: ignore[method-assign]

        result = asyncio.run(
            cap.run_goal(
                goal="abrir example",
                intent_class="realizar_pesquisa",
                context={
                    "session_id": "sess-1",
                    "work_id": "work-1",
                    "callbacks": {"send_status": lambda phase, payload=None: None},
                },
            )
        )
        assert result.get("ok") is True

