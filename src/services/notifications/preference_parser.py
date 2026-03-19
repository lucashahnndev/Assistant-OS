import re
from typing import Any, Dict, Optional


def _int_or_none(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


class PreferenceParser:
    """
    Phase-0 parser for explicit user preference commands (PT/EN).
    This parser is intentionally conservative to avoid false positives.
    """

    _PATTERNS = [
        # Channel: block push
        (
            re.compile(
                r"\b(?:n[aã]o\s+(?:me\s+)?(?:mande|envie|dispare).*(?:push|notifica[cç][aã]o)|sem\s+push|don't\s+send\s+me\s+push)\b",
                re.IGNORECASE,
            ),
            {
                "dimension": "channel",
                "key": "allow_push",
                "value": False,
                "priority": "hard",
                "scope": {"type": "global"},
                "impact_level": "medium",
            },
        ),
        # Timing: default reminder lead minutes
        (
            re.compile(
                r"\b(?:me\s+avise\s+sempre|avise\s+sempre|always\s+remind\s+me)\s+(\d{1,3})\s*(?:min|mins|minutos?)\s*(?:antes|before)?\b",
                re.IGNORECASE,
            ),
            {
                "dimension": "timing",
                "key": "default_reminder_offset_minutes",
                "priority": "hard",
                "scope": {"type": "global"},
                "impact_level": "medium",
            },
        ),
        # Interruptibility
        (
            re.compile(
                r"\b(?:n[aã]o\s+me\s+interrompa\s+enquanto\s+estou\s+conversando|don't\s+interrupt\s+me\s+while\s+i\s+am\s+chatting)\b",
                re.IGNORECASE,
            ),
            {
                "dimension": "interruptibility",
                "key": "allow_interrupt_active_conversation",
                "value": False,
                "priority": "hard",
                "scope": {"type": "global"},
                "impact_level": "medium",
            },
        ),
        # Style: concise/direct
        (
            re.compile(
                r"\b(?:seja\s+mais\s+direto(?:\s+nas\s+mensagens)?|evite\s+mensagens\s+longas|be\s+more\s+direct|keep\s+it\s+short)\b",
                re.IGNORECASE,
            ),
            {
                "dimension": "style",
                "key": "style_mode",
                "value": "direct_concise",
                "priority": "soft",
                "scope": {"type": "global"},
                "impact_level": "low",
            },
        ),
    ]

    @classmethod
    def parse(cls, text: str) -> Optional[Dict[str, Any]]:
        raw = str(text or "").strip()
        if not raw:
            return None
        for pattern, template in cls._PATTERNS:
            m = pattern.search(raw)
            if not m:
                continue
            parsed = dict(template)
            if parsed.get("dimension") == "timing" and parsed.get("key") == "default_reminder_offset_minutes":
                minutes = _int_or_none(m.group(1) if m.lastindex else "")
                if minutes is None:
                    return None
                parsed["value"] = max(1, min(720, minutes))
            parsed["source"] = "explicit_user_command"
            parsed["raw_text"] = raw
            return parsed
        return None
