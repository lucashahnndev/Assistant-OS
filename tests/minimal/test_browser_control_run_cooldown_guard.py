import asyncio

from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability


class _KernelStub:
    config = {"agent": {"agent_name": "Test"}}


class _ErrResp:
    def model_dump(self, mode="json"):
        _ = mode
        return {"status": "error", "error_details": "planner_error_simulated"}


class _SubagentErr:
    def __init__(self):
        self.calls = 0

    async def run_to_goal(self, *args, **kwargs):
        _ = (args, kwargs)
        self.calls += 1
        return _ErrResp()

    def get_last_vision_observation(self):
        return {}


def _delegated_ctx():
    return {
        "session_id": "sess-cooldown",
        "work_id": "work-cooldown",
        "execution_context_envelope": {
            "action_id": "browser.control.run",
            "delegation": {
                "delegation_id": "deleg-1",
                "child_agent_id": "browser_subagent_executor",
            },
        },
    }


def test_run_goal_blocks_immediate_retry_after_same_goal_failure():
    cap = BrowserControlCapability(
        _KernelStub(),
        {
            "policy_enabled": False,
            "registry_enabled": False,
            "run_failure_cooldown_seconds": 120,
        },
    )
    cap._runtime = object()
    sub = _SubagentErr()
    cap._subagent = sub

    async def _noop_ensure_runtime(**kwargs):
        _ = kwargs
        return None

    cap._ensure_runtime = _noop_ensure_runtime  # type: ignore[method-assign]

    first = asyncio.run(
        cap.run_goal(
            goal="abrir amazon",
            intent_class="automacao_ui",
            context=_delegated_ctx(),
        )
    )
    assert first.get("ok") is False
    assert sub.calls == 1

    second = asyncio.run(
        cap.run_goal(
            goal="abrir amazon",
            intent_class="automacao_ui",
            context=_delegated_ctx(),
        )
    )
    assert second.get("ok") is False
    assert second.get("error_code") == "BROWSER_RUN_COOLDOWN"
    assert sub.calls == 1


def test_run_goal_blocks_parallel_active_run_per_session():
    cap = BrowserControlCapability(_KernelStub(), {"run_failure_cooldown_seconds": 0})
    cap._active_run_by_session["sess-cooldown"] = 123.0
    out = asyncio.run(
        cap.run_goal(
            goal="abrir amazon",
            intent_class="automacao_ui",
            context=_delegated_ctx(),
        )
    )
    assert out.get("ok") is False
    assert out.get("error_code") == "BROWSER_RUN_ALREADY_ACTIVE"
