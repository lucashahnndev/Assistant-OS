from typing import List, Dict, Any, Optional
import json
import requests
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider, ProviderContractError
from utils.logging_config import get_logger

logger = get_logger("OllamaDriver")

class OllamaProvider(ILLMProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if config:
            self.api_url = config.get("base_url") or config.get("url") or "http://localhost:11434/api/chat"
            self.model = config.get("model", "llama3")
            self.max_tokens = int(config.get("max_tokens", 4096))
        else:
            self.api_url = "http://localhost:11434/api/chat"
            self.model = "llama3"
            self.max_tokens = 4096

    @staticmethod
    def _normalize_response_text(value: Any, fallback: str = "") -> str:
        if isinstance(value, str):
            return value
        if value is None:
            return fallback
        if isinstance(value, dict):
            candidate = value.get("text") or value.get("response") or value.get("message")
            if candidate is not None:
                return str(candidate)
            try:
                return json.dumps(value, ensure_ascii=False)
            except Exception:
                return str(value)
        if isinstance(value, list):
            try:
                return json.dumps(value, ensure_ascii=False)
            except Exception:
                return str(value)
        return str(value)

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] | None = None, **kwargs) -> AgentIntent:
        # Construct messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        user_message = {"role": "user", "content": user_input}
        if attachments:
            user_message["images"] = attachments
        messages.append(user_message)

        schema = AgentIntent.model_json_schema()
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "options": {
                "temperature": 0.0,
                "num_predict": kwargs.get("max_tokens", self.max_tokens)
            }
        }

        try:
            response = requests.post(self.api_url, json=payload)
            response.raise_for_status()
            result = response.json()
            content = ""
            if isinstance(result, dict):
                if isinstance(result.get("message"), dict):
                    content = result.get("message", {}).get("content", "") or ""
                elif isinstance(result.get("choices"), list) and result["choices"]:
                    first_choice = result["choices"][0]
                    if isinstance(first_choice, dict):
                        message = first_choice.get("message", {})
                        if isinstance(message, dict):
                            content = message.get("content", "") or ""
                    elif hasattr(first_choice, "message"):
                        content = getattr(first_choice.message, "content", "") or ""
            content = str(content or "{}")
            
            try:
                data = json.loads(content)
                if not isinstance(data, dict):
                    raise ValueError("Model returned a non-object JSON payload.")
                attachments = data.get("attachments")
                if not attachments and isinstance(data.get("params"), dict):
                    attachments = data.get("params", {}).get("attachments")
                action = str(data.get("action", "") or "").strip()
                if not action:
                    raise ILLMProvider.contract_error(
                        "Ollama intent missing action.",
                        provider_used="ollama",
                        error_stage="provider",
                        error_type="provider_contract_error",
                        error_reason="missing_action",
                        raw_response=data,
                        provider_parse_status="missing_action",
                        provider_fallback_reason="provider_contract_error",
                        provider_schema_mode="intent_json",
                        provider_contract_mode="intent",
                        extra={"diagnostic_source": "ollama"},
                    )
                response_text = self._normalize_response_text(data.get("response_text", data.get("reply", "")), fallback="")
                if action == "reply" and not response_text.strip():
                    raise ILLMProvider.contract_error(
                        "Ollama reply missing response_text.",
                        provider_used="ollama",
                        error_stage="provider",
                        error_type="provider_contract_error",
                        error_reason="missing_response_text",
                        raw_response=data,
                        provider_parse_status="missing_response_text",
                        provider_fallback_reason="provider_contract_error",
                        provider_schema_mode="intent_json",
                        provider_contract_mode="intent",
                        extra={"diagnostic_source": "ollama"},
                    )
                allowed_actions = kwargs.get("allowed_actions")
                if isinstance(allowed_actions, (list, tuple, set)):
                    allowed = {str(item).strip() for item in allowed_actions if str(item or "").strip()}
                    if allowed and action not in allowed:
                        raise ILLMProvider.contract_error(
                            f"Ollama returned unsupported action: {action}.",
                            provider_used="ollama",
                            error_stage="provider",
                            error_type="provider_contract_error",
                            error_reason="unsupported_action",
                            raw_response=data,
                            provider_parse_status="unsupported_action",
                            provider_fallback_reason="provider_contract_error",
                            provider_schema_mode="intent_json",
                            provider_contract_mode="intent",
                            extra={"diagnostic_source": "ollama"},
                        )

                return AgentIntent(
                    thought=str(data.get("thought", "") or ""),
                    action=action,
                    params=data.get("params", {}),
                    response_text=response_text,
                    attachments=attachments
                )
            except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
                raise ILLMProvider.contract_error(
                    "Ollama structured output is not valid JSON.",
                    provider_used="ollama",
                    error_stage="provider",
                    error_type="provider_exception",
                    error_reason="invalid_json",
                    raw_response=content,
                    provider_parse_status="invalid_json",
                    provider_fallback_reason="provider_parse_error",
                    provider_schema_mode="intent_json",
                    provider_contract_mode="intent",
                    extra={"diagnostic_source": "ollama"},
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
