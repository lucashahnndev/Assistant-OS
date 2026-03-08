import re
from typing import Any, Dict, List


def _clip(text: str, max_len: int = 280) -> str:
    value = str(text or "").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 3].rstrip() + "..."


def _extract_coordinates(text: str) -> List[Dict[str, Any]]:
    value = str(text or "")
    coords: List[Dict[str, Any]] = []

    # Pattern: "X: 123 Y: 456" or "x=123, y=456"
    for m in re.finditer(r"[xX]\s*[:=]\s*(\d{1,4})[^\d]+[yY]\s*[:=]\s*(\d{1,4})", value):
        x = int(m.group(1))
        y = int(m.group(2))
        if 0 <= x <= 1000 and 0 <= y <= 1000:
            coords.append({"x": x, "y": y, "label": "vision_hint", "source": "xy_pair"})

    # Pattern: "(123, 456)" plain pair
    for m in re.finditer(r"\((\d{1,4})\s*,\s*(\d{1,4})\)", value):
        x = int(m.group(1))
        y = int(m.group(2))
        if 0 <= x <= 1000 and 0 <= y <= 1000:
            coords.append({"x": x, "y": y, "label": "vision_hint", "source": "tuple_pair"})

    # Deduplicate
    seen = set()
    unique: List[Dict[str, Any]] = []
    for c in coords:
        key = (c["x"], c["y"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return unique[:8]


def format_vision_for_prompt(observation: Dict[str, Any]) -> str:
    summary = _clip(str(observation.get("summary") or ""))
    coords = observation.get("coordinates") if isinstance(observation.get("coordinates"), list) else []
    if not coords:
        return f"Vision: {summary}" if summary else "Vision: no additional visual details."
    pairs = ", ".join([f"({int(c.get('x', 0))},{int(c.get('y', 0))})" for c in coords[:4]])
    if summary:
        return f"Vision: {summary} | Coords: {pairs}"
    return f"Vision Coords: {pairs}"


def normalize_vision_observation(raw: Any, *, goal: str = "", url: str = "") -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "schema": "browser_control.vision.v1",
        "goal": str(goal or ""),
        "url": str(url or ""),
        "summary": "",
        "coordinates": [],
        "raw_text": "",
        "prompt_view": "",
    }

    if isinstance(raw, dict):
        summary = str(raw.get("summary") or raw.get("description") or raw.get("message") or "").strip()
        raw_text = str(raw.get("raw_text") or summary or "").strip()
        coords = raw.get("coordinates")
        if not isinstance(coords, list):
            coords = _extract_coordinates(raw_text)
        base["summary"] = _clip(summary or raw_text)
        base["coordinates"] = coords
        base["raw_text"] = _clip(raw_text, 4000)
        base["prompt_view"] = format_vision_for_prompt(base)
        return base

    raw_text = str(raw or "").strip()
    base["raw_text"] = _clip(raw_text, 4000)
    base["coordinates"] = _extract_coordinates(raw_text)
    # Keep summary compact and useful for history/prompt.
    summary = raw_text.split("\n", 1)[0].strip()
    base["summary"] = _clip(summary if summary else raw_text)
    base["prompt_view"] = format_vision_for_prompt(base)
    return base
