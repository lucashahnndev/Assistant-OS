from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageColor, ImageDraw, ImageFont


def _parse_color(value: Any, opacity: float) -> Tuple[int, int, int, int]:
    raw = str(value or "#00E5FF").strip()
    try:
        rgb = ImageColor.getrgb(raw)
    except Exception:
        rgb = (0, 229, 255)
    alpha = int(max(0.0, min(1.0, float(opacity))) * 255)
    return int(rgb[0]), int(rgb[1]), int(rgb[2]), alpha


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _draw_focus_corners(draw: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float, color: Tuple[int, int, int, int], stroke: int) -> None:
    x2 = x + max(1.0, w)
    y2 = y + max(1.0, h)
    corner = max(8.0, min(24.0, min(max(1.0, w), max(1.0, h)) * 0.35))

    draw.line([(x, y), (x + corner, y)], fill=color, width=stroke)
    draw.line([(x, y), (x, y + corner)], fill=color, width=stroke)

    draw.line([(x2, y), (x2 - corner, y)], fill=color, width=stroke)
    draw.line([(x2, y), (x2, y + corner)], fill=color, width=stroke)

    draw.line([(x, y2), (x + corner, y2)], fill=color, width=stroke)
    draw.line([(x, y2), (x, y2 - corner)], fill=color, width=stroke)

    draw.line([(x2, y2), (x2 - corner, y2)], fill=color, width=stroke)
    draw.line([(x2, y2), (x2, y2 - corner)], fill=color, width=stroke)


def _draw_arrow(draw: ImageDraw.ImageDraw, x: float, y: float, x2: float, y2: float, color: Tuple[int, int, int, int], stroke: int) -> None:
    draw.line([(x, y), (x2, y2)], fill=color, width=stroke)
    angle = math.atan2(y2 - y, x2 - x)
    length = 12.0
    a1 = angle + math.pi * 0.82
    a2 = angle - math.pi * 0.82
    p1 = (x2 + length * math.cos(a1), y2 + length * math.sin(a1))
    p2 = (x2 + length * math.cos(a2), y2 + length * math.sin(a2))
    draw.line([(x2, y2), p1], fill=color, width=stroke)
    draw.line([(x2, y2), p2], fill=color, width=stroke)


def render_overlay_debug_image(
    *,
    reference_image_path: str,
    command: Dict[str, Any],
    output_path: str | None = None,
) -> Dict[str, Any]:
    """
    Renders an overlay debug frame on top of a reference screenshot.
    This uses the same command payload sent to the live overlay backend.
    """
    if not reference_image_path or not os.path.isfile(reference_image_path):
        return {
            "ok": False,
            "status": "error",
            "error": "DEBUG_REFERENCE_NOT_FOUND",
            "text": f"Reference image not found: {reference_image_path}",
        }

    try:
        base = Image.open(reference_image_path).convert("RGBA")
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer, "RGBA")

        ctype = str(command.get("type") or "").strip().lower()
        x = _coerce_float(command.get("x"))
        y = _coerce_float(command.get("y"))
        w = _coerce_float(command.get("width"))
        h = _coerce_float(command.get("height"))
        stroke = max(1, int(_coerce_float(command.get("stroke_width"), 3)))
        opacity = max(0.0, min(1.0, _coerce_float(command.get("opacity"), 0.95)))
        color = _parse_color(command.get("color"), opacity)

        if ctype == "draw_rect":
            draw.rectangle([x, y, x + max(1.0, w), y + max(1.0, h)], outline=color, width=stroke)
        elif ctype == "draw_focus_corners":
            _draw_focus_corners(draw, x, y, w, h, color, stroke)
        elif ctype == "draw_circle":
            radius = _coerce_float(command.get("radius"), max(w, h) / 2.0 if max(w, h) > 0 else 18.0)
            cx = x if w <= 0 else (x + w / 2.0)
            cy = y if h <= 0 else (y + h / 2.0)
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=color, width=stroke)
        elif ctype == "draw_line":
            x2 = _coerce_float(command.get("x2"), x)
            y2 = _coerce_float(command.get("y2"), y)
            draw.line([(x, y), (x2, y2)], fill=color, width=stroke)
        elif ctype == "draw_arrow":
            x2 = _coerce_float(command.get("x2"), x)
            y2 = _coerce_float(command.get("y2"), y)
            _draw_arrow(draw, x, y, x2, y2, color, stroke)
        elif ctype == "draw_text":
            text = str(command.get("text") or "")
            font_size = max(10, int(_coerce_float(command.get("font_size"), 20)))
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()
            draw.text((x, y), text, fill=color, font=font)
        elif ctype == "draw_path":
            points = command.get("points") if isinstance(command.get("points"), list) else []
            normalized: List[Tuple[float, float]] = []
            for p in points:
                if isinstance(p, dict):
                    normalized.append((_coerce_float(p.get("x")), _coerce_float(p.get("y"))))
            if len(normalized) >= 2:
                draw.line(normalized, fill=color, width=stroke)

        composed = Image.alpha_composite(base, layer).convert("RGB")
        if not output_path:
            root, ext = os.path.splitext(reference_image_path)
            suffix = str(command.get("id") or int(time.time() * 1000))
            out_ext = ext if ext.lower() in {".png", ".jpg", ".jpeg"} else ".png"
            output_path = f"{root}.overlay_debug.{suffix}{out_ext}"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        composed.save(output_path)
        return {
            "ok": True,
            "status": "success",
            "path": os.path.abspath(output_path),
            "text": "Overlay debug image rendered.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "error": "DEBUG_RENDER_FAILED",
            "text": str(exc),
        }
