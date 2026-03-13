from src.capabilities.browser_control.planner import BrowserSubagent


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


def test_click_visual_receipt_rejects_sponsored_target():
    result_data = {
        "hit_after": {
            "top_text": "Playlist oficial\nPatrocinado",
            "has_interactive_ancestor": False,
            "interactive_tag": "",
            "top_tag": "div",
        }
    }
    assessment = BrowserSubagent._assess_click_visual_receipt(result_data)
    assert assessment.get("ok") is False
    assert "sponsored" in str(assessment.get("reason"))


def test_click_visual_receipt_rejects_generic_interactive_ancestor():
    result_data = {
        "hit_after": {
            "top_text": "Artistas populares",
            "has_interactive_ancestor": True,
            "interactive_tag": "main",
            "top_tag": "div",
        }
    }
    assessment = BrowserSubagent._assess_click_visual_receipt(result_data)
    assert assessment.get("ok") is False
    assert "too generic" in str(assessment.get("reason"))


def test_click_visual_receipt_accepts_actionable_target():
    result_data = {
        "hit_after": {
            "top_text": "Coldplay - Viva La Vida",
            "has_interactive_ancestor": True,
            "interactive_tag": "a",
            "top_tag": "span",
        }
    }
    assessment = BrowserSubagent._assess_click_visual_receipt(result_data)
    assert assessment.get("ok") is True
