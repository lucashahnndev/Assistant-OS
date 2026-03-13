import json
import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("OpenAIParser")

def extract_and_parse_json(content: str) -> Dict[str, Any]:
    """
    Standardized JSON extraction for OpenAI responses.
    """
    if not isinstance(content, str):
        return {}
    text = content.strip()
    if not text:
        return {}

    if text.startswith("```"):
        fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Brace counting fallback
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            # Try to parse from this brace onwards
            rem = text[idx:]
            obj = json.loads(rem)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            # If loads fails, it might still have extra data, 
            # but we'll try a more manual approach if raw_decode is problematic
            try:
                obj, _ = json.JSONDecoder().raw_decode(text[idx:])
                if isinstance(obj, dict):
                    return obj
            except:
                continue
    return {}
