import asyncio

from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability


class _KernelStub:
    config = {"agent": {"agent_name": "Test"}}


def test_browser_launch_is_denied_without_delegated_browser_executor():
    cap = BrowserControlCapability(_KernelStub(), {"require_delegated_executor_for_browser_launch": True})
    out = asyncio.run(
        cap.run_goal(
            goal="abrir https://example.com",
            intent_class="realizar_pesquisa",
            context={
                "session_id": "sess-1",
                "work_id": "work-1",
                "execution_context_envelope": {
                    "action_id": "browser.control.run",
                    "delegation": {
                        "delegation_id": "deleg-1",
                        "child_agent_id": "main_orchestrator",
                    },
                },
            },
        )
    )
    assert out.get("ok") is False
    assert out.get("error_code") == "BROWSER_LAUNCH_NOT_DELEGATED"


def test_browser_launch_allows_delegated_browser_executor():
    cap = BrowserControlCapability(_KernelStub(), {"require_delegated_executor_for_browser_launch": True})
    assert cap._is_browser_launch_authorized(
        {
            "execution_context_envelope": {
                "action_id": "browser.control.run",
                "delegation": {
                    "delegation_id": "deleg-2",
                    "child_agent_id": "browser_subagent_executor",
                },
            }
        }
    ) is True


def test_browser_launch_denied_without_envelope_when_delegation_required():
    cap = BrowserControlCapability(_KernelStub(), {"require_delegated_executor_for_browser_launch": True})
    assert cap._is_browser_launch_authorized({}) is False


def test_browser_launch_allows_explicit_local_override():
    cap = BrowserControlCapability(_KernelStub(), {"require_delegated_executor_for_browser_launch": True})
    assert cap._is_browser_launch_authorized({"allow_local_browser_launch": True}) is True
