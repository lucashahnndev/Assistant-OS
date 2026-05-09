from typing import List, Dict, Any, Optional
import requests
import json
from core.intent import AgentIntent
from core.errors import SyntaxError as AgentSyntaxError, ErrorCode
from drivers.llm.base import ILLMProvider
import requests
from utils.logging_config import get_logger

logger = get_logger("OllamaDriver")

class OllamaProvider(ILLMProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if config:
            self.api_url = config.get("url", "http://localhost:11434/api/chat")
            self.model = config.get("model", "llama3")
            self.max_tokens = int(config.get("max_tokens", 4096))
        else:
            self.api_url = "http://localhost:11434/api/chat"
            self.model = "llama3"
            self.max_tokens = 4096

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] | None = None, **kwargs) -> AgentIntent:
        # Construct messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        user_message = {"role": "user", "content": user_input}
        if attachments:
            user_message["images"] = attachments
        messages.append(user_message)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "num_predict": kwargs.get("max_tokens", self.max_tokens)
            }
        }

        try:
            response = requests.post(self.api_url, json=payload)
            response.raise_for_status()
            result = response.json()
            
            content = result.get("message", {}).get("content", "{}")
            
            try:
                data = json.loads(content)
                attachments = data.get("attachments")
                if not attachments and isinstance(data.get("params"), dict):
                    attachments = data.get("params", {}).get("attachments")
                normalized_attachments: Optional[List[str]] = None
                if isinstance(attachments, str) and attachments.strip():
                    normalized_attachments = [attachments.strip()]
                elif isinstance(attachments, list):
                    cleaned = [str(x).strip() for x in attachments if str(x).strip()]
                    normalized_attachments = cleaned or None

                logger.info(
                    "Ollama parsed intent | syntax_valid=true action_candidate=%s",
                    str(data.get("action", "") or "").strip(),
                )
                return AgentIntent(
                    thought=str(data.get("thought", "") or ""),
                    action=str(data.get("action", "") or "").strip(),
                    params=data.get("params", {}) if isinstance(data.get("params", {}), dict) else {},
                    response_text=str(data.get("response_text", "") or ""),
                    attachments=normalized_attachments
                )
            except json.JSONDecodeError:
                raise AgentSyntaxError(
                    "Ollama structured output is not valid JSON.",
                    code=ErrorCode.PLANNER_INVALID_JSON,
                )

        except Exception as e:
            logger.error(f"Ollama Error: {e}")
            raise e

    def generate_text(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        """Generates plain text using Ollama."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": kwargs.get("max_tokens", self.max_tokens)
                }
            }
            
            response = requests.post(self.api_url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            return data['message']['content'].strip() if 'message' in data else "ERROR_EMPTY_RESPONSE"
        except Exception as e:
            logger.error(f"Ollama generate_text error: {e}")
            raise e
