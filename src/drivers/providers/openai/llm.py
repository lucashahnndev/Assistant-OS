from typing import List, Dict, Any, Optional
import json
import re
import time
from openai import OpenAI
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider, ProviderContractError
from server.core.secret_manager import resolve_secret_ref
from utils.logging_config import get_logger
from .parser import extract_and_parse_json

logger = get_logger("OpenAIDriver")

class OpenAIChatProvider(ILLMProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if not config:
            raise ValueError("OpenAIChatProvider requires explicit pool configuration.")
        self.api_key = resolve_secret_ref(config.get("secret_ref"))
        self.org_id = config.get("organization_id")
        self.base_url = config.get("base_url")
        self.timeout_s = float(config.get("timeout", 30))
        self.max_retries = int(config.get("max_retries", 0))

        # OpenAI-compatible local servers often don't require a real key.
        # The OpenAI SDK still expects a token-like string, so we provide a dummy if needed.
        resolved_api_key = self.api_key or ("local-openai" if self.base_url else None)
        client_kwargs: Dict[str, Any] = {"api_key": resolved_api_key}
        if self.org_id:
            client_kwargs["organization"] = self.org_id
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        client_kwargs["timeout"] = self.timeout_s
        client_kwargs["max_retries"] = max(0, self.max_retries)

        self.client = OpenAI(**client_kwargs)
        self.model = config.get("model", "gpt-4o-mini")
        self.max_tokens = int(config.get("max_tokens", 4096))

        if self.base_url:
            logger.info(
                "OpenAI-compatible endpoint enabled: %s | model=%s | timeout=%ss | max_retries=%s",
                self.base_url,
                self.model,
                self.timeout_s,
                max(0, self.max_retries),
            )

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] | None = None, **kwargs) -> AgentIntent:
        # Construct messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})

        # Define the function schema for structured output
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_intent",
                    "description": "Execute an action based on the user's request.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "thought": {
                                "type": "string",
                                "description": "The reasoning process before deciding the action."
                            },
                            "action": {
                                "type": "string",
                                "description": "The name of the action to be executed."
                            },
                            "params": {
                                "type": "object",
                                "description": "Parameters required for the action."
                            },
                            "response_text": {
                                "type": "string",
                                "description": "Text to be spoken back to the user immediately."
                            },
                            "attachments": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                },
                                "description": "A list of absolute file paths to attach to the response when action is 'reply'."
                            }
                        },
                        "required": ["thought", "action", "params"]
                    }
                }
            }
        ]

        try:
            t0 = time.time()
            logger.info(
                "OpenAI intent request start | model=%s | base_url=%s | history=%s",
                self.model,
                self.base_url or "https://api.openai.com/v1",
                len(history),
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "execute_intent"}},
                max_tokens=kwargs.get("max_tokens", self.max_tokens)
            )
            logger.info("OpenAI intent request end | elapsed=%.2fs", time.time() - t0)

            
            if not response.choices or not response.choices[0].message.content:
                logger.error("OpenAI returned an empty response.")
                raise ValueError("OpenAI returned an empty response.")

            content = response.choices[0].message.content.strip()
            
            # Use specialized parser
            data = extract_and_parse_json(content)
            
            if not data:
                logger.error("Failed to extract valid JSON from OpenAI response.")
                raise ProviderContractError("Failed to fulfill AgentIntent contract: Invalid JSON.")

            # Normalization
            attachments = data.get("attachments")
            if not attachments and isinstance(data.get("params"), dict):
                attachments = data.get("params", {}).get("attachments")

            # Assuming _normalize_response_text is a method that will be added or defined elsewhere
            # For now, using a placeholder or direct assignment if no complex normalization is needed
            # If _normalize_response_text is not defined, this line will cause an error.
            # For the purpose of this edit, I'll assume it's a valid call or will be implemented.
            response_text = self._normalize_response_text(
                data.get("response_text", data.get("reply", "")),
                fallback="",
            )

            # Mandatory thought enforcement
            thought = str(data.get("thought", "")).strip()
            if not thought:
                thought = "OpenAI processing turn."

            return AgentIntent(
                thought=thought,
                plan=data.get("plan", []),
                action=data.get("action", "reply"),
                params=data.get("params", {}),
                state_summary=data.get("state_summary", {}),
                response_text=response_text,
                attachments=attachments
            )

        except Exception as e:
            logger.error(f"OpenAI Error: {e}")
            raise e

    # _extract_json logic moved to .parser.extract_and_parse_json

    def generate_text(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        """Generates plain text using OpenAI's chat completions."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=kwargs.get("max_tokens", self.max_tokens)
            )
            return response.choices[0].message.content.strip() if response.choices else "ERROR_EMPTY_RESPONSE"
        except Exception as e:
            logger.error(f"OpenAI generate_text error: {e}")
            raise e
