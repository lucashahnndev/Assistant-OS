from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.skills.assistive_overlay.debug_render import render_overlay_debug_image
from src.skills.assistive_overlay.skill import AssistiveOverlaySkill


def test_render_overlay_debug_image_draws_and_saves(tmp_path: Path):
    ref_path = tmp_path / "ref.png"
    Image.new("RGB", (400, 300), color=(20, 20, 20)).save(ref_path)

    result = render_overlay_debug_image(
        reference_image_path=str(ref_path),
        command={
            "type": "draw_rect",
            "id": "dbg-1",
            "x": 100,
            "y": 80,
            "width": 120,
            "height": 60,
            "color": "#00E5FF",
            "stroke_width": 3,
            "opacity": 0.95,
        },
    )

    assert result.get("ok") is True
    out_path = Path(str(result.get("path")))
    assert out_path.exists()
    assert out_path.name != ref_path.name


def test_highlight_target_returns_debug_image_path_when_debug_enabled(tmp_path: Path):
    ref_path = tmp_path / "vision_locator.png"
    Image.new("RGB", (800, 600), color=(10, 10, 10)).save(ref_path)

    class _FakeRenderer:
        def draw(self, command_type, payload):
            command = dict(payload)
            command["type"] = command_type
            command.setdefault("id", "overlay-debug")
            return {"ok": True, "backend": "noop", "command": command}

        def clear_by_id(self, _command_id):
            return {"ok": True, "backend": "noop"}

        def clear_all(self):
            return {"ok": True, "backend": "noop", "cleared": 0}

    class _FakeLocator:
        def locate(self, **_kwargs):
            return {
                "ok": True,
                "bbox": {
                    "label": "target",
                    "x": 200,
                    "y": 120,
                    "width": 80,
                    "height": 40,
                    "screen_id": 0,
                },
                "screenshot_path": str(ref_path),
            }

    skill = AssistiveOverlaySkill(kernel=SimpleNamespace(), config={"overlay": {"backend": "noop", "debug": {"enabled": True}}})
    skill.renderer = _FakeRenderer()
    skill.locator = _FakeLocator()

    result = skill.execute(
        "overlay.assist.highlight_target",
        {"label": "botao enviar", "mark_type": "rect"},
        {"session_id": "s1"},
    )

    assert result.get("ok") is True
    debug_path = result.get("debug_image_path")
    assert isinstance(debug_path, str) and debug_path
    assert Path(debug_path).exists()
