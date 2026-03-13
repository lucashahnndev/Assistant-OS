import os
import sys
import tempfile
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.capabilities.vision.capability import VisionCapability


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
        path = tf.name
    Image.new("RGB", (1280, 720), color=(0, 0, 0)).save(path)

    try:
        payload = '{"found":true,"label":"volume","confidence":0.9,"x":10,"y":20,"width":30,"height":40,"screen_id":1}'
        capability = VisionCapability(kernel=_Kernel(payload, path), config={})
        result = capability.execute("vision.locate_screen", {"label": "volume icon"}, {"session_id": "s1"})

        assert result["ok"] is True
        assert result["bbox"]["label"] == "volume"
        assert result["bbox"]["screen_id"] == 1
        assert result["bbox"]["coordinate_space"] == "normalized_1000"
    finally:
        os.unlink(path)


def test_locate_screen_handles_not_found():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        path = tf.name
    Image.new("RGB", (1280, 720), color=(0, 0, 0)).save(path)

    try:
        payload = '{"found":false,"label":"volume","confidence":0.2,"x":0,"y":0,"width":0,"height":0,"screen_id":0}'
        capability = VisionCapability(kernel=_Kernel(payload, path), config={})
        result = capability.execute("vision.locate_screen", {"label": "volume icon"}, {"session_id": "s1"})

        assert result["ok"] is False
        assert result["error"] == "ELEMENT_NOT_FOUND"
    finally:
        os.unlink(path)


def test_locate_screen_not_found_has_no_hardcoded_secondary_strategies():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        path = tf.name
    Image.new("RGB", (1920, 1080), color=(0, 0, 0)).save(path)

    class _FakeLLMSeq:
        def __init__(self):
            self.calls = 0

        def analyze_image(self, image_path: str, prompt: str):
            self.calls += 1
            return '{"found":false,"label":"volume icon","confidence":0.0,"x":0,"y":0,"width":0,"height":0}'

    kernel = _Kernel('{"found":true}', path)
    kernel.llm_manager = _FakeLLMSeq()
    capability = VisionCapability(kernel=kernel, config={})
    result = capability.execute("vision.locate_screen", {"label": "icone do volume"}, {"session_id": "s1"})

    assert result["ok"] is False
    assert result["error"] == "ELEMENT_NOT_FOUND"
    assert kernel.llm_manager.calls == 1
    os.unlink(path)


def test_locate_screen_accepts_target_alias():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        path = tf.name
    Image.new("RGB", (1280, 720), color=(0, 0, 0)).save(path)

    try:
        payload = '{"found":true,"label":"clock","confidence":0.92,"x":100,"y":200,"width":120,"height":40,"screen_id":0}'
        capability = VisionCapability(kernel=_Kernel(payload, path), config={})
        result = capability.execute("vision.locate_screen", {"target": "system clock date"}, {"session_id": "s1"})

        assert result["ok"] is True
        assert result["bbox"]["label"] == "clock"
    finally:
        os.unlink(path)


def test_locate_screen_rejects_bbox_far_out_of_frame():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        path = tf.name
    Image.new("RGB", (1280, 720), color=(0, 0, 0)).save(path)

    class _FakeLLMSeq:
        def __init__(self):
            self.calls = 0

        def analyze_image(self, image_path: str, prompt: str):
            self.calls += 1
            if self.calls == 1:
                return '{"found":true,"label":"send","confidence":0.9,"x":844,"y":828,"width":34,"height":34,"screen_id":0}'
            return '{"found":true,"label":"send","confidence":0.7,"x":10000,"y":10000,"width":34,"height":34,"screen_id":0}'

    kernel = _Kernel('{"found":true}', path)
    kernel.llm_manager = _FakeLLMSeq()
    capability = VisionCapability(kernel=kernel, config={})
    result = capability.execute("vision.locate_screen", {"label": "send icon"}, {"session_id": "s1"})

    assert result["ok"] is False
    assert result["error"] == "ELEMENT_OUT_OF_FRAME"

    os.unlink(path)


def test_locate_screen_recovers_bbox_with_dpi_scale():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        path = tf.name
    Image.new("RGB", (1280, 720), color=(0, 0, 0)).save(path)

    try:
        # Typical scaling mismatch example: coordinates produced in ~1.25x space.
        payload = '{"found":true,"label":"send","confidence":0.9,"x":1000,"y":825,"width":40,"height":40,"screen_id":0}'
        capability = VisionCapability(kernel=_Kernel(payload, path), config={})
        result = capability.execute("vision.locate_screen", {"label": "send icon"}, {"session_id": "s1"})

        assert result["ok"] is True
        assert result.get("corrected") is True
        assert result["bbox_px"]["y"] < 720
        assert result["bbox_px"]["x"] < 1280
    finally:
        os.unlink(path)




def test_locate_screen_converts_normalized_1000_coordinates():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        path = tf.name
    Image.new("RGB", (1280, 720), color=(0, 0, 0)).save(path)

    class _FakeLLMSeq:
        def __init__(self):
            self.calls = 0

        def analyze_image(self, image_path: str, prompt: str):
            self.calls += 1
            if self.calls == 1:
                return '{"found":true,"label":"send icon","confidence":0.95,"x":820,"y":760,"width":22,"height":22,"screen_id":0,"coordinate_space":"normalized_1000"}'
            if self.calls == 2:
                return '{"grounded":true,"visible_text":"send icon","icon_shape":"paper plane","input_nearby":true,"confidence":0.95,"reason":"icon looks like send"}'
            if self.calls == 3:
                return '{"is_send_icon":true,"has_composer":true,"confidence":0.9,"reason":"composer clearly adjacent"}'
            if self.calls == 4:
                return '{"relation_valid":true,"has_input":true,"distance_px":18,"confidence":0.92,"reason":"right side of composer","input_bbox":{"x":300,"y":520,"width":730,"height":28}}'
            return '{"found":true,"label":"send icon","confidence":0.93,"x":822,"y":758,"width":22,"height":22,"screen_id":0,"coordinate_space":"normalized_1000"}'

    kernel = _Kernel('{"found":true}', path)
    kernel.llm_manager = _FakeLLMSeq()
    capability = VisionCapability(kernel=kernel, config={})
    result = capability.execute(
        "vision.locate_screen",
        {"label": "botão de enviar mensagem"},
        {"session_id": "s1"},
    )

    assert result["ok"] is True
    assert result.get("corrected") is True
    assert result.get("detected_coordinate_space") in {"normalized_1000", "heuristic_1000_grid"}
    assert float(result["bbox_px"]["x"]) > 1000.0
    os.unlink(path)


def test_locate_screen_converts_center_anchor_to_top_left():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        path = tf.name
    Image.new("RGB", (1280, 720), color=(0, 0, 0)).save(path)

    try:
        payload = (
            '{"found":true,"label":"volume icon","confidence":0.95,'
            '"x":820,"y":760,"width":22,"height":22,'
            '"coordinate_space":"normalized_1000","origin":"center"}'
        )
        capability = VisionCapability(kernel=_Kernel(payload, path), config={})
        result = capability.execute("vision.locate_screen", {"label": "volume icon"}, {"session_id": "s1"})

        assert result["ok"] is True
        # Center->top-left conversion should move x/y left/up by half bbox size.
        assert float(result["bbox"]["x"]) < 820.0
        assert float(result["bbox"]["y"]) < 760.0
    finally:
        os.unlink(path)
