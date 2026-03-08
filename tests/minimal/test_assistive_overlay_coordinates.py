from src.skills.assistive_overlay.intent import build_draw_payload_from_box
from src.skills.assistive_overlay.locator import VisionLocator
from src.skills.vision.skill import VisionSkill
from src.skills.assistive_overlay.backends.qt_process import _map_point_to_window_local


def test_build_draw_payload_prefers_screen_space_with_screen_id():
    payload = build_draw_payload_from_box(
        mark_type="draw_focus_corners",
        located={
            "label": "network icon",
            "x": 919.0,
            "y": 881.0,
            "width": 32.0,
            "height": 32.0,
            "screen_id": 1,
        },
        params={},
        default_ttl_ms=2200,
    )
    assert payload["screen_id"] == 1
    assert payload["coordinate_space"] == "screen"


def test_build_draw_payload_keeps_explicit_global_coordinate_space():
    payload = build_draw_payload_from_box(
        mark_type="draw_rect",
        located={
            "label": "target",
            "x": 2500.0,
            "y": 800.0,
            "width": 50.0,
            "height": 40.0,
            "screen_id": 1,
        },
        params={"coordinate_space": "global"},
        default_ttl_ms=2200,
    )
    assert payload["coordinate_space"] == "global"


def test_build_draw_payload_does_not_force_screen_id_when_missing():
    payload = build_draw_payload_from_box(
        mark_type="draw_rect",
        located={
            "label": "target",
            "x": 120.0,
            "y": 220.0,
            "width": 30.0,
            "height": 20.0,
        },
        params={},
        default_ttl_ms=2200,
    )
    assert "screen_id" not in payload
    assert payload["coordinate_space"] == "global"


def test_map_point_global_to_local_normal_case():
    x, y = _map_point_to_window_local(
        x=2500.0,
        y=800.0,
        coordinate_space="global",
        origin_x=1920.0,
        origin_y=0.0,
        screen_width=1920.0,
        screen_height=1080.0,
    )
    assert x == 580.0
    assert y == 800.0


def test_map_point_global_falls_back_when_point_looks_local():
    x, y = _map_point_to_window_local(
        x=919.0,
        y=881.0,
        coordinate_space="global",
        origin_x=1920.0,
        origin_y=0.0,
        screen_width=1920.0,
        screen_height=1080.0,
    )
    assert x == 919.0
    assert y == 881.0


def test_locator_normalize_bbox_does_not_force_screen_id():
    bbox = VisionLocator._normalize_bbox(
        {"label": "target", "x": 10, "y": 20, "width": 30, "height": 40},
        fallback_label="target",
    )
    assert "screen_id" not in bbox


def test_vision_normalize_bbox_does_not_force_screen_id():
    bbox = VisionSkill._normalize_bbox(
        {"label": "target", "x": 10, "y": 20, "width": 30, "height": 40},
        fallback_label="target",
    )
    assert "screen_id" not in bbox
