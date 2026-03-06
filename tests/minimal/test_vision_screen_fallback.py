import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.skills.vision.skill import VisionSkill


class _FakeSystemDriver:
    def __init__(self, screenshot_path: str):
        self._screenshot_path = screenshot_path
        self.called = False

    def take_screenshot(self, filename="vision_temp.png", session_id=None):
        self.called = True
        return self._screenshot_path


class _FakeLLM:
    def analyze_image(self, image_path: str, prompt: str):
        return "Resumo: há uma interface de chat aberta em tema escuro."


class _Kernel:
    def __init__(self, screenshot_path: str):
        self.llm_manager = _FakeLLM()
        self.system_driver = _FakeSystemDriver(screenshot_path)


def test_analyze_without_image_path_falls_back_to_search_screen_for_screen_request():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"fake")
        path = tf.name

    try:
        kernel = _Kernel(path)
        skill = VisionSkill(kernel=kernel, config={})
        result = skill.execute(
            "vision.analyze",
            {"prompt": "descreva resumidamente a minha tela"},
            {"session_id": "s1", "user_input": "atlas, descreva a minha tela"},
        )

        assert result["ok"] is True
        assert kernel.system_driver.called is True
        assert result.get("path") == path
    finally:
        os.unlink(path)


def test_analyze_without_image_path_keeps_error_for_non_screen_request():
    kernel = _Kernel("/tmp/not-used.png")
    skill = VisionSkill(kernel=kernel, config={})
    result = skill.execute("vision.analyze", {"prompt": "analise este arquivo"}, {"session_id": "s1"})
    assert result["ok"] is False
    assert result["error"] == "MISSING_IMAGE_PATH"
