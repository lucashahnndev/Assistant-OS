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

    def take_screenshot(self, filename="vision_temp.png", session_id=None):
        return self._screenshot_path


class _FakeLLM:
    def __init__(self, payload: str):
        self.payload = payload

    def analyze_image(self, image_path: str, prompt: str):
        return self.payload


class _Kernel:
    def __init__(self, llm_payload: str, screenshot_path: str):
        self.llm_manager = _FakeLLM(llm_payload)
        self.system_driver = _FakeSystemDriver(screenshot_path)


def test_locate_screen_parses_json_payload():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"fake")
        path = tf.name

    try:
        payload = '{"found":true,"label":"volume","confidence":0.9,"x":10,"y":20,"width":30,"height":40,"screen_id":1}'
        skill = VisionSkill(kernel=_Kernel(payload, path), config={})
        result = skill.execute("vision.locate_screen", {"label": "volume icon"}, {"session_id": "s1"})

        assert result["ok"] is True
        assert result["bbox"]["label"] == "volume"
        assert result["bbox"]["screen_id"] == 1
    finally:
        os.unlink(path)


def test_locate_screen_handles_not_found():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"fake")
        path = tf.name

    try:
        payload = '{"found":false,"label":"volume","confidence":0.2,"x":0,"y":0,"width":0,"height":0,"screen_id":0}'
        skill = VisionSkill(kernel=_Kernel(payload, path), config={})
        result = skill.execute("vision.locate_screen", {"label": "volume icon"}, {"session_id": "s1"})

        assert result["ok"] is False
        assert result["error"] == "ELEMENT_NOT_FOUND"
    finally:
        os.unlink(path)


def test_locate_screen_accepts_target_alias():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"fake")
        path = tf.name

    try:
        payload = '{"found":true,"label":"clock","confidence":0.92,"x":100,"y":200,"width":120,"height":40,"screen_id":0}'
        skill = VisionSkill(kernel=_Kernel(payload, path), config={})
        result = skill.execute("vision.locate_screen", {"target": "system clock date"}, {"session_id": "s1"})

        assert result["ok"] is True
        assert result["bbox"]["label"] == "clock"
    finally:
        os.unlink(path)
