from src.capabilities.browser_control.planner import BrowserSubagent


class _RuntimeStub:
    target_id = ""


def test_loop_guard_resets_recovery_attempts_when_state_changes():
    agent = BrowserSubagent(_RuntimeStub(), object())
    agent._forced_recovery_attempts = 2
    out = agent._evaluate_loop_guard(
        action="wait",
        goal="abrir youtube",
        state={"url": "https://www.youtube.com", "title": "YouTube", "candidates": []},
        state_changed=True,
    )
    assert out.get("mode") == "none"
    assert agent._forced_recovery_attempts == 0


def test_loop_guard_forces_recovery_before_hard_stop():
    agent = BrowserSubagent(_RuntimeStub(), object(), max_forced_recovery_attempts=2)
    agent._consecutive_same_state = 6
    agent._consecutive_same_action = 0

    out = agent._evaluate_loop_guard(
        action="vision",
        goal="buscar controle ps4 amazon",
        state={"url": "https://www.amazon.com", "title": "Amazon", "candidates": []},
        state_changed=False,
    )
    assert out.get("mode") == "force_recovery"
    assert str(out.get("recovery_action") or "") in {"vision", "scroll", "navigate"}
    assert agent._forced_recovery_attempts == 1


def test_loop_guard_hard_stop_after_recovery_budget_exhausted():
    agent = BrowserSubagent(_RuntimeStub(), object(), max_forced_recovery_attempts=1)
    agent._consecutive_same_state = 6
    agent._consecutive_same_action = 4

    first = agent._evaluate_loop_guard(
        action="wait",
        goal="qualquer",
        state={"url": "about:blank", "title": "", "candidates": []},
        state_changed=False,
    )
    assert first.get("mode") == "force_recovery"

    second = agent._evaluate_loop_guard(
        action="wait",
        goal="qualquer",
        state={"url": "about:blank", "title": "", "candidates": []},
        state_changed=False,
    )
    assert second.get("mode") == "hard_stop"
    assert "Loop guard hard-stop" in str(second.get("reason") or "")
