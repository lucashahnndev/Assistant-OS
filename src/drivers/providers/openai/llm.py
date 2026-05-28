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
        self.org_id = resolve_secret_ref(config.get("organization_id"))
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

    @staticmethod
    def _extract_response_content(message: Any) -> str:
        if message is None:
            return ""
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
        tool_calls = getattr(message, "tool_calls", None)
        if isinstance(tool_calls, list) and tool_calls:
            first_call = tool_calls[0]
            function_obj = getattr(first_call, "function", None)
            arguments = getattr(function_obj, "arguments", None)
            if isinstance(arguments, str) and arguments.strip():
                return arguments.strip()
            if isinstance(arguments, dict):
                try:
                    return json.dumps(arguments, ensure_ascii=False)
                except Exception:
                    return str(arguments)
            if isinstance(first_call, dict):
                function_dict = first_call.get("function") if isinstance(first_call.get("function"), dict) else {}
                arguments = function_dict.get("arguments")
                if isinstance(arguments, str) and arguments.strip():
                    return arguments.strip()
                if isinstance(arguments, dict):
                    try:
                        return json.dumps(arguments, ensure_ascii=False)
                    except Exception:
                        return str(arguments)
        return ""

    @staticmethod
    def _build_response_format(allowed_actions: Optional[List[str]] = None) -> Dict[str, Any]:
        schema = AgentIntent.model_json_schema()
        allowed = [str(x).strip() for x in (allowed_actions or []) if str(x or "").strip()]
        if allowed and isinstance(schema.get("properties"), dict):
            action_schema = schema["properties"].get("action")
            if isinstance(action_schema, dict):
                current_enum = action_schema.get("enum")
                merged: List[str] = []
                if isinstance(current_enum, list):
                    merged.extend(str(item).strip() for item in current_enum if str(item or "").strip())
                for item in allowed:
                    if item not in merged:
                        merged.append(item)
                action_schema["enum"] = merged
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "agent_intent",
                "schema": schema,
                "strict": True,
            },
        }

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
        allowed_actions = kwargs.get("allowed_actions")
        response_format = self._build_response_format(allowed_actions if isinstance(allowed_actions, list) else None)

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
                response_format=response_format,
                max_tokens=kwargs.get("max_tokens", self.max_tokens)
            )
            logger.info("OpenAI intent request end | elapsed=%.2fs", time.time() - t0)

            if not response.choices:
                logger.error("OpenAI returned an empty response.")
                raise ValueError("OpenAI returned an empty response.")

            content = self._extract_response_content(response.choices[0].message)
            if not content:
                logger.error("OpenAI returned an empty response payload.")
                raise ValueError("OpenAI returned an empty response payload.")
            
            # Use specialized parser
            data = extract_and_parse_json(content)
            
            if not data:
                logger.error("Failed to extract valid JSON from OpenAI response.")
                raise ProviderContractError("Failed to fulfill AgentIntent contract: Invalid JSON.")

            # Normalization
            attachments = data.get("attachments")
            if not attachments and isinstance(data.get("params"), dict):
                attachments = data.get("params", {}).get("attachments")
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
            if "response_format" in str(e).lower() or "json_schema" in str(e).lower() or "format" in str(e).lower():
                logger.warning("OpenAI intent request rejected structured response_format; retrying without it: %s", e)
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice={"type": "function", "function": {"name": "execute_intent"}},
                    max_tokens=kwargs.get("max_tokens", self.max_tokens),
                )
                if not response.choices:
                    logger.error("OpenAI returned an empty response.")
                    raise ValueError("OpenAI returned an empty response.")
                content = self._extract_response_content(response.choices[0].message)
                if not content:
                    logger.error("OpenAI returned an empty response payload.")
                    raise ValueError("OpenAI returned an empty response payload.")
                data = extract_and_parse_json(content)
                if not data:
                    logger.error("Failed to extract valid JSON from OpenAI response.")
                    raise ProviderContractError("Failed to fulfill AgentIntent contract: Invalid JSON.")
                attachments = data.get("attachments")
                if not attachments and isinstance(data.get("params"), dict):
                    attachments = data.get("params", {}).get("attachments")
                response_text = self._normalize_response_text(
                    data.get("response_text", data.get("reply", "")),
                    fallback="",
                )
                thought = str(data.get("thought", "")).strip() or "OpenAI processing turn."
                return AgentIntent(
                    thought=thought,
                    plan=data.get("plan", []),
                    action=data.get("action", "reply"),
                    params=data.get("params", {}),
                    state_summary=data.get("state_summary", {}),
                    response_text=response_text,
                    attachments=attachments
                )
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
