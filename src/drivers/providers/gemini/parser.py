import json
import logging
import re
from typing import Any, Dict

from core.errors import SyntaxError as AgentSyntaxError, ErrorCode

logger = logging.getLogger("GeminiParser")

def _strip_fences(text: str) -> str:
    raw = str(text or "").strip()
    if not raw.startswith("```"):
        return raw
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()

def extract_and_parse_json(content: str, *, strict: bool = False) -> Dict[str, Any]:
    """
    Extracts and parses JSON from Gemini's response.
    Only fence stripping and direct JSON parsing are allowed.
    """
    if not isinstance(content, str):
        raise AgentSyntaxError("Gemini structured output must be a string.", code=ErrorCode.PLANNER_INVALID_JSON)
    if not content.strip():
        raise AgentSyntaxError("Gemini structured output is empty.", code=ErrorCode.PLANNER_INVALID_JSON)

    text = _strip_fences(content)
    if not text:
        raise AgentSyntaxError("Gemini structured output is empty.", code=ErrorCode.PLANNER_INVALID_JSON)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentSyntaxError(
            f"Gemini structured output is not valid JSON: {exc.msg}",
            code=ErrorCode.PLANNER_INVALID_JSON,
        ) from exc

    if not isinstance(parsed, dict):
        raise AgentSyntaxError("Gemini structured output must be a JSON object.", code=ErrorCode.PLANNER_INVALID_JSON)
    return parsed
