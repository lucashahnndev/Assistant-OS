from __future__ import annotations

from typing import Any, Dict


def normalize_mark_type(raw: Any) -> str:
    value = str(raw or "focus_corners").strip().lower()
    aliases = {
        "focus": "draw_focus_corners",
        "corners": "draw_focus_corners",
        "target": "draw_focus_corners",
        "circle": "draw_circle",
        "rect": "draw_rect",
        "rectangle": "draw_rect",
        "line": "draw_line",
        "arrow": "draw_arrow",
        "text": "draw_text",
        "path": "draw_path",
        "draw_focus_corners": "draw_focus_corners",
        "draw_circle": "draw_circle",
        "draw_rect": "draw_rect",
        "draw_line": "draw_line",
        "draw_arrow": "draw_arrow",
        "draw_text": "draw_text",
        "draw_path": "draw_path",
    }
    return aliases.get(value, "draw_focus_corners")


def build_draw_payload_from_box(
    *,
    mark_type: str,
    located: Dict[str, Any],
    params: Dict[str, Any],
    default_ttl_ms: int,
) -> Dict[str, Any]:
    x = float(located.get("x") or 0)
    y = float(located.get("y") or 0)
    width = float(located.get("width") or 0)
    height = float(located.get("height") or 0)

    located_screen_id = located.get("screen_id") if isinstance(located, dict) else None
    param_screen_id = params.get("screen_id")
    screen_id = None
    if located_screen_id is not None:
        try:
            screen_id = int(located_screen_id)
        except Exception:
            screen_id = None
    elif param_screen_id is not None:
        try:
            screen_id = int(param_screen_id)
        except Exception:
            screen_id = None

    explicit_coordinate_space = str(params.get("coordinate_space") or located.get("coordinate_space") or "").strip().lower()
    if explicit_coordinate_space in {"global", "screen", "local"}:
        coordinate_space = "screen" if explicit_coordinate_space == "local" else explicit_coordinate_space
    else:
        # Locator bbox values are usually monitor-local when a screen_id is provided.
        coordinate_space = "screen" if (located_screen_id is not None) else "global"

    payload: Dict[str, Any] = {
        "id": params.get("id") or f"target-{str(located.get('label') or 'item').strip().lower().replace(' ', '-')}",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "color": params.get("color") or "#00E5FF",
        "stroke_width": int(params.get("stroke_width") or 3),
        "opacity": float(params.get("opacity") or 0.95),
        "ttl_ms": int(params.get("ttl_ms") or default_ttl_ms),
        "pulse": bool(params.get("pulse", True)),
        "coordinate_space": coordinate_space,
    }
    if screen_id is not None:
        payload["screen_id"] = screen_id

    if mark_type == "draw_circle":
        payload["radius"] = float(params.get("radius") or max(width, height) / 2.0 or 18.0)
    elif mark_type == "draw_arrow":
        payload["x2"] = float(params.get("x2") or (x + width / 2.0))
        payload["y2"] = float(params.get("y2") or (y + height / 2.0))
        payload["x"] = float(params.get("from_x") or x - max(24.0, width))
        payload["y"] = float(params.get("from_y") or y - max(24.0, height))
    elif mark_type == "draw_line":
        payload["x2"] = float(params.get("x2") or (x + width))
        payload["y2"] = float(params.get("y2") or (y + height))
    elif mark_type == "draw_text":
        payload["text"] = str(params.get("text") or params.get("instruction") or located.get("label") or "")
        payload["font_size"] = int(params.get("font_size") or 20)
        payload["y"] = float(params.get("y") or max(22.0, y - 14.0))
    elif mark_type == "draw_path":
        payload["points"] = params.get("points") if isinstance(params.get("points"), list) else [
            {"x": x, "y": y},
            {"x": x + width, "y": y},
            {"x": x + width, "y": y + height},
            {"x": x, "y": y + height},
            {"x": x, "y": y},
        ]

    return payload
