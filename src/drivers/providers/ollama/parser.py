import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("OllamaParser")

def extract_and_parse_json(content: str) -> Dict[str, Any]:
    """
    Standardized JSON extraction for Ollama.
    Ollama often returns JSON mode, but we still use brace counting for safety.
    """
    if not content:
        return {}
    
    text = content.strip()
    try:
        # Fast path
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Robust path: scan for the first decodable object
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return {}
