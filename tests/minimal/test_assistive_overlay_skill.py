import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.capabilities.assistive_overlay.capability import AssistiveOverlayCapability
from src.capabilities.vision.capability import VisionCapability


class _FakeSystemDriver:
    def __init__(self, screenshot_path: str):
        self._screenshot_path = screenshot_path

    def take_screenshot(self, filename="overlay.png", session_id=None):
        return self._screenshot_path


class _FakeLLMManager:
    def analyze_image(self, image_path: str, prompt: str):
        return {
            "found": True,
            "label": "volume icon",
            "confidence": 0.93,
            "x": 1810,
            "y": 1048,
            "width": 34,
            "height": 34,
            "screen_id": 0,
        }


class _FakeKernel:
    def __init__(self, screenshot_path: str):
        self.llm_manager = _FakeLLMManager()
        self.system_driver = _FakeSystemDriver(screenshot_path)


class _FakeRegistry:
    def __init__(self, vision_capability: VisionCapability):
        self._vision_capability = vision_capability

    def get_capability_for_action(self, action_id: str):
        if action_id == "vision.locate_screen":
            return self._vision_capability
        return None

    def dispatch(self, action_id: str, params, context):
        if action_id == "vision.locate_screen":
            return self._vision_capability.execute(action_id, params, context)
        return {"ok": False, "status": "error", "error": "UNKNOWN_ACTION", "text": action_id}


def _make_capability(tmp_file: str) -> AssistiveOverlayCapability:
    kernel = _FakeKernel(tmp_file)
    return AssistiveOverlayCapability(
        kernel=kernel,
        config={
            "backend": "noop",
            "default_ttl_ms": 1200,
            "allow_wayland": False,
            "overlay": {"backend": "noop", "default_ttl_ms": 1200},
        },
    )


def test_draw_and_clear_noop_backend():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"fake")
        path = tf.name

    try:
        capability = _make_capability(path)

        draw = capability.execute(
            "overlay.assist.draw_rect",
            {
                "id": "target-volume",
                "x": 1810,
                "y": 1048,
                "width": 34,
                "height": 34,
                "color": "#00E5FF",
                "stroke_width": 3,
                "opacity": 0.95,
                "ttl_ms": 2200,
                "pulse": True,
                "screen_id": 0,
            },
            context={"session_id": "s1"},
        )

        assert draw["ok"] is True
        assert draw["id"] == "target-volume"

        cleared = capability.execute(
            "overlay.assist.clear_by_id",
            {"id": "target-volume"},
            context={"session_id": "s1"},
        )
        assert cleared["ok"] is True
    finally:
        os.unlink(path)


def test_draw_without_screen_id_does_not_force_zero():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"fake")
        path = tf.name

    try:
        capability = _make_capability(path)
        draw = capability.execute(
            "overlay.assist.draw_rect",
            {"x": 120.0, "y": 220.0, "width": 30.0, "height": 20.0},
            context={"session_id": "s1"},
        )
        assert draw["ok"] is True
        command = draw.get("command") if isinstance(draw.get("command"), dict) else {}
        assert "screen_id" not in command
    finally:
        os.unlink(path)


def test_highlight_target_pipeline_with_locator():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"fake")
        path = tf.name

    try:
        capability = _make_capability(path)
        result = capability.execute(
            "overlay.assist.highlight_target",
            {
                "label": "volume icon",
                "mark_type": "focus_corners",
                "color": "#00E5FF",
                "ttl_ms": 2200,
                "pulse": True,
            },
            context={"session_id": "s1"},
        )

        assert result["ok"] is True
        assert result["target"]["label"] == "volume icon"
        assert result["draw"]["type"] == "draw_focus_corners"
    finally:
        os.unlink(path)


def test_highlight_target_prefers_vision_contract_route():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"fake")
        path = tf.name

    try:
        kernel = _FakeKernel(path)
        vision_capability = VisionCapability(kernel=kernel, config={})
        registry = _FakeRegistry(vision_capability)

        capability = AssistiveOverlayCapability(
            kernel=kernel,
            config={
                "backend": "noop",
                "default_ttl_ms": 1200,
                "allow_wayland": False,
                "overlay": {"backend": "noop", "default_ttl_ms": 1200},
            },
        )
        result = capability.execute(
            "overlay.assist.highlight_target",
            {"label": "volume icon", "mark_type": "focus_corners"},
            context={"session_id": "s1", "capability_registry": registry},
        )

        assert result["ok"] is True
        assert result["target"]["width"] == 34
    finally:
        os.unlink(path)


def test_draw_arrow_missing_coords_recovers_via_locator():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"fake")
        path = tf.name

    try:
        kernel = _FakeKernel(path)
        capability = AssistiveOverlayCapability(
            kernel=kernel,
            config={
                "backend": "noop",
                "default_ttl_ms": 1200,
                "allow_wayland": False,
                "overlay": {"backend": "noop", "default_ttl_ms": 1200},
            },
        )
        result = capability.execute(
            "overlay.assist.draw_arrow",
            {},
            context={"session_id": "s1", "user_input": "pode desenhar onde fica o botao de envio?"},
        )

        assert result["ok"] is True
        assert result.get("draw", {}).get("type") == "draw_arrow"
        assert result.get("target", {}).get("width") == 34
    finally:
        os.unlink(path)


def test_highlight_target_uses_target_description_alias():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"fake")
        path = tf.name

    try:
        capability = _make_capability(path)
        result = capability.execute(
            "overlay.assist.highlight_target",
            {
                "target_description": "system clock or date on bottom right taskbar",
                "mark_type": "focus_corners",
            },
            context={"session_id": "s1", "user_input": "por favor demarque novamente"},
        )

        assert result["ok"] is True
        # Must not use user_input sentence as target label fallback when alias is present.
        assert result["target"]["label"] != "por favor demarque novamente"
    finally:
        os.unlink(path)
