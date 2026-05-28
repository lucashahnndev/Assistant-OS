import json
import re
import logging
from typing import Dict, Any, Optional

from core.errors import SyntaxError as AgentSyntaxError

logger = logging.getLogger("OpenAIParser")

def extract_and_parse_json(content: str, strict: bool = False) -> Dict[str, Any]:
    """
    Standardized JSON extraction for OpenAI responses.
    """
    if not isinstance(content, str):
        return {}
    text = content.strip()
    if not text:
        return {}

    # 1. Remove <think> blocks if present
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()

    # 2. Extract from markdown fences even if there is introductory text
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 3. Fallback: Find the first '{' and try to decode a JSON object from there
    for idx, ch in enumerate(text):
        if ch == "{":
            try:
                # raw_decode parses the first valid JSON object and ignores trailing text
                obj, _ = json.JSONDecoder().raw_decode(text[idx:])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue

    if strict:
        raise AgentSyntaxError("OpenAI structured output is not valid JSON.")
    return {}
