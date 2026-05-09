from typing import List, Dict, Any, Optional
import json
import re
import time
from openai import OpenAI
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider, ProviderContractError
from server.core.secret_manager import resolve_secret_ref
from utils.logging_config import get_logger
from utils.contract_artifacts import write_contract_violation
from .parser import extract_and_parse_json
from core.errors import SyntaxError as AgentSyntaxError, ErrorCode, ProviderQuotaError, ProviderAuthError, ProviderRateLimitError
from services.agent_runtime_v2.flags import is_paranoid_mode_enabled, is_strict_mode_enabled
import openai

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
                "OpenAI-compatible endpoint enabled: %s | model=%s | timeout=%ss | max_retries=%s",
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

    def _request_with_json(self, *, messages: List[Dict[str, str]], max_tokens: int) -> Any:
        return self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=max_tokens
        )

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
                "OpenAI intent request start | model=%s | base_url=%s | history=%s | structured_mode=json",
                self.model,
                self.base_url or "https://api.openai.com/v1",
                len(history),
            )
            max_tokens = kwargs.get("max_tokens", self.max_tokens)

            response = self._request_with_json(messages=messages, max_tokens=max_tokens)
            logger.info("OpenAI intent request end | elapsed=%.2fs", time.time() - t0)

            if not response.choices:
                logger.error("OpenAI returned an empty response.")
                raise ValueError("OpenAI returned an empty response.")

            message = response.choices[0].message
            content = (message.content or "").strip() if getattr(message, "content", None) is not None else ""
            
            if not content:
                logger.error("OpenAI returned an empty response.")
                raise ValueError("OpenAI returned an empty response.")
                
            # Use specialized parser directly on the raw text content
            data = extract_and_parse_json(content, strict=True)
            
            if not data:
                content = (message.content or "").strip() if getattr(message, "content", None) is not None else ""
                logger.error("Failed to extract valid JSON from OpenAI response.")
                try:
                    raw_response = {
                        "content": (message.content or "") if getattr(message, "content", None) is not None else "",
                        "tool_calls": getattr(message, "tool_calls", None),
                    }
                    prompt_snapshot = "\n".join(
                        [f"{m.get('role')}: {m.get('content')}" for m in messages if isinstance(m, dict)]
                    )
                    write_contract_violation(
                        provider="openai",
                        model=self.model,
                        contract_name="agent_intent_v1",
                        prompt=prompt_snapshot,
                        raw_response=raw_response,
                        error_text="Failed to fulfill AgentIntent contract: Invalid JSON.",
                        attempt=1,
                        max_attempts=1,
                    )
                except Exception:
                    pass
                raise ProviderContractError("Failed to fulfill AgentIntent contract: Invalid JSON.")

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

            logger.info(
                "OpenAI parsed intent | syntax_valid=true action_candidate=%s",
                str(data.get("action", "") or "").strip(),
            )
            return AgentIntent(
                thought=str(data.get("thought", "") or ""),
                plan=normalized_plan,
                action=str(data.get("action", "") or "").strip(),
                params=params,
                state_summary=state_summary,
                task_label=task_label,
                response_text=str(data.get("response_text", data.get("reply", "")) or ""),
                attachments=normalized_attachments,
            )

        except openai.AuthenticationError as e:
            logger.error(f"OpenAI Auth Error: {e}")
            raise ProviderAuthError(str(e), provider="openai")
        except openai.RateLimitError as e:
            # Rate limit can sometimes mean quota exceeded if it's a 429 regarding insufficient quota.
            # OpenAI often uses 429 for both rate limiting and quota (though they have added 'insufficient_quota' error code)
            error_code = getattr(getattr(e, "error", None), "code", None)
            if error_code == "insufficient_quota":
                logger.error(f"OpenAI Quota Exceeded: {e}")
                raise ProviderQuotaError(str(e), provider="openai")
            logger.warning(f"OpenAI Rate Limit: {e}")
            raise ProviderRateLimitError(str(e), provider="openai")
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
