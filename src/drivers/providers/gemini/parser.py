import json
import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger("GeminiParser")

def repair_json(s: str) -> str:
    """
    Attempts to fix common JSON errors from LLM output (missing braces, unclosed strings).
    """
    stack = []
    in_string = False
    escape = False
    for char in s:
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char in '{[':
                stack.append(char)
            elif char == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
            elif char == ']':
                if stack and stack[-1] == '[':
                    stack.pop()
    
    repaired = s
    if in_string:
        repaired += '"'
    
    while stack:
        opener = stack.pop()
        repaired += '}' if opener == '{' else ']'
        
    return repaired

def _strip_fences(text: str) -> str:
    raw = str(text or "").strip()
    if not raw.startswith("```"):
        return raw
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()

def _normalize_common_issues(text: str) -> str:
    raw = str(text or "")
    # Normalize smart quotes that frequently break JSON parsing.
    return (
        raw.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .strip()
    )

def _try_parse_dict(text: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None

def _scan_first_json_dict(text: str) -> Optional[Dict[str, Any]]:
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None

def extract_and_parse_json(content: str) -> Dict[str, Any]:
    """
    Robustly extracts and parses JSON from Gemini's response.
    """
    if not isinstance(content, str):
        return {}
    if not content.strip():
        return {}

    text = _normalize_common_issues(_strip_fences(content))
    if not text:
        return {}

    try:
        # Fast path (already clean JSON object)
        parsed = _try_parse_dict(text)
        if parsed is not None:
            return parsed

        # Slice between first/last braces as common mixed-output recovery.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            parsed = _try_parse_dict(candidate)
            if parsed is not None:
                return parsed
            repaired = repair_json(candidate)
            parsed = _try_parse_dict(repaired)
            if parsed is not None:
                logger.warning("Gemini parser auto-repaired malformed JSON candidate.")
                return parsed

        # Robust scan for first decodable object in noisy text.
        scanned = _scan_first_json_dict(text)
        if scanned:
            return scanned

        # Last-chance repair from first brace onward.
        if start != -1:
            repaired_tail = repair_json(text[start:])
            parsed = _try_parse_dict(repaired_tail)
            if parsed is not None:
                logger.warning("Gemini parser auto-repaired JSON tail payload.")
                return parsed
    except Exception as e:
        logger.warning(f"Gemini Parser Error: {e}")
    logger.warning("Gemini Parser Error: unable to parse structured JSON from response.")
    return {}
