import json
import logging
from typing import Any, Dict

from core.errors import SyntaxError as AgentSyntaxError, ErrorCode

logger = logging.getLogger("OllamaParser")

def extract_and_parse_json(content: str, *, strict: bool = False) -> Dict[str, Any]:
    """
    Standardized JSON extraction for Ollama.
    Only direct JSON parsing is allowed.
    """
    if not content:
        raise AgentSyntaxError("Ollama structured output is empty.", code=ErrorCode.PLANNER_INVALID_JSON)

    text = content.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise AgentSyntaxError("Ollama structured output is not valid JSON.", code=ErrorCode.PLANNER_INVALID_JSON)

    if not isinstance(parsed, dict):
        raise AgentSyntaxError("Ollama structured output must be a JSON object.", code=ErrorCode.PLANNER_INVALID_JSON)
    return parsed
