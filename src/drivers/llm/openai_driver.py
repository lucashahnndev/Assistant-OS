from typing import List, Dict, Any, Optional
import json
import re
import time
from openai import OpenAI
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider
from utils.logging_config import get_logger

logger = get_logger("OpenAIDriver")

class OpenAIChatProvider(ILLMProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if config:
            self.api_key = config.get("api_key")
            self.org_id = config.get("organization_id")
            self.base_url = config.get("base_url")
            self.timeout_s = float(config.get("timeout", 30))
            self.max_retries = int(config.get("max_retries", 0))
        else:
            from config import ConfigManager
            cfg = ConfigManager().get_llm_config().get("providers", {}).get("openai", {})
            self.api_key = cfg.get("api_key")
            self.org_id = cfg.get("organization_id")
            self.base_url = cfg.get("base_url")
            self.timeout_s = float(cfg.get("timeout", 30))
            self.max_retries = int(cfg.get("max_retries", 0))

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
        self.model = config.get("model", "gpt-4o-mini") if config else "gpt-4o-mini"
        self.max_tokens = int(config.get("max_tokens", 4096)) if config else 4096

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

            choice = response.choices[0] if response.choices else None
            message = choice.message if choice else None
            function_args = None

            tool_calls = getattr(message, "tool_calls", None) if message else None
            if tool_calls:
                try:
                    function_args = json.loads(tool_calls[0].function.arguments)
                except Exception:
                    function_args = None

            if function_args is None:
                # Fallback for local OpenAI-like endpoints that return plain text/JSON
                content = (getattr(message, "content", "") or "").strip() if message else ""
                parsed = self._extract_json(content)
                if isinstance(parsed, dict):
                    function_args = parsed
                else:
                    function_args = {
                        "thought": "Model returned non-JSON content without tool_calls.",
                        "action": "reply",
                        "params": {},
                        "response_text": content or "Não consegui interpretar a resposta do modelo.",
                    }

            attachments = function_args.get("attachments")
            if not attachments and isinstance(function_args.get("params"), dict):
                attachments = function_args.get("params", {}).get("attachments")

            return AgentIntent(
                thought=function_args.get("thought", ""),
                action=function_args.get("action", "unknown"),
                params=function_args.get("params", {}),
                response_text=function_args.get("response_text", ""),
                attachments=attachments
            )

        except Exception as e:
            logger.error(f"OpenAI Error: {e}")
            raise e

    @staticmethod
    def _extract_json(content: str) -> Dict[str, Any] | None:
        if not isinstance(content, str):
            return None
        text = content.strip()
        if not text:
            return None

        if text.startswith("```"):
            fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
            if fence_match:
                text = fence_match.group(1).strip()

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

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
        return None

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
            return response.choices[0].message.content.strip() if response.choices else "Error: Resposta vazia da OpenAI."
        except Exception as e:
            logger.error(f"OpenAI generate_text error: {e}")
            raise e
