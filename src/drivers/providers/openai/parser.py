import json
import logging
import re
from typing import Any, Dict

from core.errors import SyntaxError as AgentSyntaxError, ErrorCode

logger = logging.getLogger("OpenAIParser")

def extract_and_parse_json(content: str, *, strict: bool = False) -> Dict[str, Any]:
    """
    Standardized JSON extraction for OpenAI responses.
    Only fence stripping and direct JSON parsing are allowed.
    """
    if not isinstance(content, str):
        raise AgentSyntaxError("OpenAI structured output must be a string.", code=ErrorCode.PLANNER_INVALID_JSON)
    text = content.strip()
    if not text:
        raise AgentSyntaxError("OpenAI structured output is empty.", code=ErrorCode.PLANNER_INVALID_JSON)

    if text.startswith("```"):
        fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()
        else:
            text = re.sub(r"^```(?:json)?\s*", "", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentSyntaxError(
            f"OpenAI structured output is not valid JSON: {exc.msg}",
            code=ErrorCode.PLANNER_INVALID_JSON,
        ) from exc

    if not isinstance(parsed, dict):
        raise AgentSyntaxError("OpenAI structured output must be a JSON object.", code=ErrorCode.PLANNER_INVALID_JSON)
    return parsed
