from typing import List, Dict, Any, Optional
import json
import re
import time
import base64
from openai import OpenAI
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider, ProviderContractError
from server.core.secret_manager import resolve_secret_ref
from utils.logging_config import get_logger
from utils.contract_artifacts import write_contract_violation
from drivers.providers.openai.parser import extract_and_parse_json
from core.errors import ErrorCode
from services.agent_runtime_v2.flags import is_paranoid_mode_enabled, is_strict_mode_enabled
import openai

logger = get_logger("LlamaServerDriver")

class LlamaServerChatProvider(ILLMProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if not config:
            raise ValueError("LlamaServerChatProvider requires explicit pool configuration.")
        self.api_key = resolve_secret_ref(config.get("secret_ref"))
        self.org_id = resolve_secret_ref(config.get("organization_id"))
        self.base_url = config.get("base_url")
        self.timeout_s = float(config.get("timeout", 30))
        self.max_retries = int(config.get("max_retries", 0))

        self.intent_repair_attempts = int(config.get("intent_repair_attempts", 1) or 1)

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
                "LlamaServer endpoint enabled: %s | model=%s | timeout=%ss | max_retries=%s",
                self.base_url,
                self.model,
                self.timeout_s,
                max(0, self.max_retries),
            )

    @staticmethod
    def _normalize_plan_field(raw_plan: Any) -> List[str]:
        out: List[str] = []

        def _walk(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, str):
                text = value.strip()
                if text:
                    out.append(text)
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    _walk(item)
                return
            text = str(value).strip()
            if text:
                out.append(text)

        _walk(raw_plan)
        return out[:16]

    def _request_with_json(self, *, messages: List[Dict[str, str]], max_tokens: int, allowed_actions: set = None) -> Any:
        schema = AgentIntent.model_json_schema()
        if allowed_actions:
            valid_actions = list(allowed_actions)
            if "reply" not in valid_actions:
                valid_actions.append("reply")
            if "error" not in valid_actions:
                valid_actions.append("error")
            if "properties" in schema and "action" in schema["properties"]:
                schema["properties"]["action"]["enum"] = valid_actions

        format_spec = {
            "type": "json_schema", 
            "json_schema": {
                "name": "agent_intent",
                "schema": schema,
                "strict": True
            }
        }
        try:
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format=format_spec,
                temperature=0,
                max_tokens=max_tokens
            )
        except Exception as e:
            if "json_schema" in str(e).lower() or "format" in str(e).lower() or "400" in str(e):
                logger.warning(f"LlamaServer strict json_schema rejected, falling back to json_object + schema: {e}")
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object", "schema": schema},
                    temperature=0,
                    max_tokens=max_tokens
                )
            raise e

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] | None = None, **kwargs) -> AgentIntent:
        # Construct messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        allowed_actions_kw = kwargs.get("allowed_actions")
        allowed_actions = (
            set(str(x).strip() for x in allowed_actions_kw if str(x or "").strip())
            if isinstance(allowed_actions_kw, (list, set, tuple))
            else set()
        )
        capability_registry = kwargs.get("capability_registry")
        strict_mode = bool(kwargs.get("strict_mode", is_strict_mode_enabled(getattr(self, "config_manager", None))))
        paranoid_mode = bool(kwargs.get("paranoid_mode", is_paranoid_mode_enabled(getattr(self, "config_manager", None))))
        strict_parsing = True

        try:
            t0 = time.time()
            logger.info(
                "LlamaServer intent request start | model=%s | base_url=%s | history=%s | structured_mode=json",
                self.model,
                self.base_url or "https://api.openai.com/v1",
                len(history),
            )
            max_tokens = kwargs.get("max_tokens", self.max_tokens)

            response = self._request_with_json(
                messages=messages, 
                max_tokens=max_tokens, 
                allowed_actions=allowed_actions
            )
            logger.info("LlamaServer intent request end | elapsed=%.2fs", time.time() - t0)

            if not response or not response.choices:
                logger.error("LlamaServer returned an empty response.")
                raise ILLMProvider.contract_error(
                    "LlamaServer returned an empty response.",
                    provider_used="llama_server",
                    error_stage="provider",
                    error_type="provider_exception",
                    error_reason="empty_output",
                    raw_response=response,
                    provider_parse_status="empty_output",
                    provider_fallback_reason="provider_empty_output",
                    provider_schema_mode="intent_json",
                    provider_contract_mode="intent",
                    extra={"diagnostic_source": "llama_server"},
                )

            message = response.choices[0].message
            content = (message.content or "").strip() if getattr(message, "content", None) is not None else ""
            
            if not content:
                logger.error("LlamaServer returned an empty response.")
                raise ILLMProvider.contract_error(
                    "LlamaServer returned an empty response.",
                    provider_used="llama_server",
                    error_stage="provider",
                    error_type="provider_exception",
                    error_reason="empty_output",
                    raw_response=content,
                    provider_parse_status="empty_output",
                    provider_fallback_reason="provider_empty_output",
                    provider_schema_mode="intent_json",
                    provider_contract_mode="intent",
                    extra={"diagnostic_source": "llama_server"},
                )
                
            # Use specialized parser directly on the raw text content
            data = extract_and_parse_json(content)
            
            if not data:
                logger.error("Failed to extract valid JSON from LlamaServer response.")
                raise ILLMProvider.contract_error(
                    "Failed to fulfill AgentIntent contract: Invalid JSON.",
                    provider_used="llama_server",
                    error_stage="provider",
                    error_type="provider_exception",
                    error_reason="invalid_json",
                    raw_response=content,
                    provider_parse_status="invalid_json",
                    provider_fallback_reason="provider_parse_error",
                    provider_schema_mode="intent_json",
                    provider_contract_mode="intent",
                    extra={"diagnostic_source": "llama_server"},
                )

            attachments_value = data.get("attachments")
            normalized_attachments: Optional[List[str]] = None
            if isinstance(attachments_value, list):
                cleaned = [str(x).strip() for x in attachments_value if str(x).strip()]
                normalized_attachments = cleaned or None
            elif isinstance(attachments_value, str) and attachments_value.strip():
                normalized_attachments = [attachments_value.strip()]

            params = data.get("params", {})
            if not isinstance(params, dict):
                params = {}

            state_summary = data.get("state_summary", {})
            if not isinstance(state_summary, dict):
                state_summary = {}

            plan_value = data.get("plan", [])
            normalized_plan = self._normalize_plan_field(plan_value) if isinstance(plan_value, (list, tuple)) else []

            task_label = data.get("task_label")
            if task_label is not None:
                task_label = str(task_label)
            action = str(data.get("action", "") or "").strip()
            if not action:
                raise ILLMProvider.contract_error(
                    "LlamaServer intent missing action.",
                    provider_used="llama_server",
                    error_stage="provider",
                    error_type="provider_contract_error",
                    error_reason="missing_action",
                    raw_response=data,
                    provider_parse_status="missing_action",
                    provider_fallback_reason="provider_contract_error",
                    provider_schema_mode="intent_json",
                    provider_contract_mode="intent",
                    extra={"diagnostic_source": "llama_server"},
                )
            response_text = str(data.get("response_text", data.get("reply", "")) or "")
            if action == "reply" and not response_text.strip():
                raise ILLMProvider.contract_error(
                    "LlamaServer reply missing response_text.",
                    provider_used="llama_server",
                    error_stage="provider",
                    error_type="provider_contract_error",
                    error_reason="missing_response_text",
                    raw_response=data,
                    provider_parse_status="missing_response_text",
                    provider_fallback_reason="provider_contract_error",
                    provider_schema_mode="intent_json",
                    provider_contract_mode="intent",
                    extra={"diagnostic_source": "llama_server"},
                )
            if isinstance(allowed_actions, (list, tuple, set)):
                allowed = {str(item).strip() for item in allowed_actions if str(item or "").strip()}
                if allowed and action not in allowed:
                    raise ILLMProvider.contract_error(
                        f"LlamaServer returned unsupported action: {action}.",
                        provider_used="llama_server",
                        error_stage="provider",
                        error_type="provider_contract_error",
                        error_reason="unsupported_action",
                        raw_response=data,
                        provider_parse_status="unsupported_action",
                        provider_fallback_reason="provider_contract_error",
                        provider_schema_mode="intent_json",
                        provider_contract_mode="intent",
                        extra={"diagnostic_source": "llama_server"},
                    )

            logger.info(
                "LlamaServer parsed intent | syntax_valid=true action_candidate=%s",
                action,
            )
            intent = AgentIntent(
                thought=str(data.get("thought", "") or ""),
                plan=normalized_plan,
                action=action,
                params=params,
                state_summary=state_summary,
                task_label=task_label,
                response_text=response_text,
                attachments=normalized_attachments,
                model_used=self.model
            )
            return intent

        except openai.AuthenticationError as e:
            logger.error(f"LlamaServer Auth Error: {e}")
            raise e
        except openai.RateLimitError as e:
            logger.warning(f"LlamaServer Rate Limit: {e}")
            raise e
        except Exception as e:
            logger.error(f"LlamaServer Error: {e}")
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
            logger.error(f"LlamaServer generate_text error: {e}")
            raise e

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """
        Analyzes an image using local Llama-Server (OpenAI-compatible vision API).
        """
        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode("utf-8")

            # Determine mime type from extension
            ext = image_path.split(".")[-1].lower()
            mime_type = "image/jpeg"
            if ext == "png":
                mime_type = "image/png"
            elif ext == "gif":
                mime_type = "image/gif"
            elif ext == "webp":
                mime_type = "image/webp"

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            },
                        },
                    ],
                }
            ]

            t0 = time.time()
            logger.info("LlamaServer vision request start | model=%s | path=%s", self.model, image_path)
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=0
            )
            
            logger.info("LlamaServer vision request end | elapsed=%.2fs", time.time() - t0)
            
            if not response or not response.choices:
                return "ERROR_EMPTY_RESPONSE"
                
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LlamaServer analyze_image error: {e}")
            return f"Error: Falha na análise local de imagem: {str(e)}"
