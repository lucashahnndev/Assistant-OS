import json
import re
import logging
from typing import Dict, Any, Optional

from core.errors import SyntaxError as AgentSyntaxError

logger = logging.getLogger("OpenRouterParser")

def repair_json(s: str) -> str:
    """
    Repair heuristic: aggressive bracket balancing for truncated outputs.
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

def extract_and_parse_json(content: str, strict: bool = False) -> Dict[str, Any]:
    """
    Extracts and parses the first JSON object found in model output, with repair heuristic.
    """
    if not isinstance(content, str):
        return {}

    text = content.strip()
    if not text:
        return {}

    # Common model pattern: fenced JSON block
    if text.startswith("```"):
        fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()
        else:
            # Truncated fence
            text = re.sub(r"^```(?:json)?\s*", "", text).strip()

    # Fast path: try pure JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        # Try repairing first
        repaired_text = repair_json(text)
        try:
            parsed = json.loads(repaired_text)
            if isinstance(parsed, dict):
                logger.warning("Auto-repaired truncated JSON response successfully.")
                return parsed
        except json.JSONDecodeError as e:
            logger.debug(f"JSON Parse Error (even after repair): {e.msg}")

    # Robust path: scan for the first decodable object in mixed text
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
            # Fallback to potentially more complex extraction or repair
            try:
                # If absolute raw_decode is needed, use it directly to satisfy linter
                obj, _ = json.JSONDecoder().raw_decode(text[idx:])
                if isinstance(obj, dict):
                    return obj
            except:
                # Try repairing this specific substring
                try:
                    repaired_sub = repair_json(text[idx:])
                    obj = json.loads(repaired_sub)
                    if isinstance(obj, dict):
                        return obj
                except:
                    continue
    if strict:
        raise AgentSyntaxError("OpenRouter structured output is not valid JSON.")
    return {}
