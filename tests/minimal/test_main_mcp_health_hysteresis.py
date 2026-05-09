from src.main import evaluate_mcp_health_streak


def test_mcp_health_streak_resets_on_healthy_probe():
    streak, should_stop = evaluate_mcp_health_streak(
        healthy=True,
        required=True,
        streak=2,
        stop_threshold=3,
    )
    assert streak == 0
    assert should_stop is False


def test_mcp_health_streak_needs_consecutive_failures_before_stop():
    streak, should_stop = evaluate_mcp_health_streak(
        healthy=False,
        required=True,
        streak=0,
        stop_threshold=3,
    )
    assert streak == 1
    assert should_stop is False

    streak, should_stop = evaluate_mcp_health_streak(
        healthy=False,
        required=True,
        streak=streak,
        stop_threshold=3,
    )
    assert streak == 2
    assert should_stop is False

    streak, should_stop = evaluate_mcp_health_streak(
        healthy=False,
        required=True,
        streak=streak,
        stop_threshold=3,
    )
    assert streak == 3
    assert should_stop is True

