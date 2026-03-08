from src.skills.browser_control.planner import BrowserSubagent


class _RuntimeStub:
    target_id = ""


def test_click_visual_prefers_explicit_args():
    agent = BrowserSubagent(_RuntimeStub(), object())
    agent._last_vision_observation = {"coordinates": [{"x": 900, "y": 900}]}
    resolved = agent._resolve_click_visual_coords({"x": 123, "y": 456}) or {}
    assert resolved.get("x") == 123
    assert resolved.get("y") == 456
    assert resolved.get("source") == "args"


def test_click_visual_uses_vision_fallback_when_args_invalid():
    agent = BrowserSubagent(_RuntimeStub(), object())
    agent._last_vision_observation = {"coordinates": [{"x": 812, "y": 134}]}
    resolved = agent._resolve_click_visual_coords({"x": -1, "y": None}) or {}
    assert resolved.get("x") == 812
    assert resolved.get("y") == 134
    assert resolved.get("source") == "vision_fallback"
