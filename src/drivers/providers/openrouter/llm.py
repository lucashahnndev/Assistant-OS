from typing import List, Dict, Any, Optional
import json
import re
import time
import uuid
from openai import OpenAI
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider, ProviderContractError
from server.core.secret_manager import resolve_secret_ref
from utils.logging_config import get_logger
from utils.contract_artifacts import write_contract_violation
from .parser import extract_and_parse_json
from core.errors import SyntaxError as AgentSyntaxError, ErrorCode, ProviderQuotaError, ProviderAuthError, ProviderRateLimitError
import openai
logger = get_logger("OpenRouterDriver")

class OpenRouterProvider(ILLMProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if not config:
            raise ValueError("OpenRouterProvider requires explicit pool configuration.")
        cfg = config
        # OpenRouter uses the same library/protocol as OpenAI
        self.api_key = resolve_secret_ref(cfg.get('secret_ref'))
        self.model = cfg.get('model', 'openai/gpt-3.5-turbo') # Default

        timeout_cfg = cfg.get("timeout", 30)
        try:
            self.timeout = float(timeout_cfg)
        except Exception:
            self.timeout = 30.0

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
            timeout=self.timeout,
        )
        # Vision models on free/low-credit accounts frequently fail with high max_tokens.
        # Keep a conservative default and allow override per provider config.
        vision_tokens = cfg.get("vision_max_tokens") or cfg.get("max_tokens") or 512
        self.vision_max_tokens = int(vision_tokens)
        self.intent_repair_attempts = int(cfg.get("intent_repair_attempts", 1) or 1)

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] | None = None, **kwargs) -> AgentIntent:
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

        req_id = uuid.uuid4().hex[:8]
        max_tokens = int(kwargs.get("max_tokens", self.vision_max_tokens))
        sys_tok = self._estimate_tokens(system_prompt)
        user_tok = self._estimate_tokens(user_input)
        history_tok = sum(self._estimate_tokens(str(m.get("content", ""))) for m in history)
        est_prompt_tokens = sys_tok + history_tok + user_tok
        request_started_at = time.perf_counter()

        logger.info(
            "OpenRouter Request Started | ReqId: %s | Model: %s | History: %d messages | MaxTokens: %d | EstPromptTokens: %d (system=%d history=%d user=%d)",
            req_id,
            self.model,
            len(history),
            max_tokens,
            est_prompt_tokens,
            sys_tok,
            history_tok,
            user_tok,
        )

        try:
            # Core is responsible for system prompt instructions
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                timeout=self.timeout,
                response_format={"type": "json_object"},
                extra_headers={
                    "HTTP-Referer": "https://github.com/lucas-openclaw/aosd", # Optional: Change to your site
                    "X-Title": "Assistant OS"
                },
                max_tokens=max_tokens
            )

            duration_ms = int((time.perf_counter() - request_started_at) * 1000)
            
            if not response.choices or not response.choices[0].message.content:
                logger.error("OpenRouter returned an empty response.")
                raise ValueError("Provider returned an empty response.")

            content = response.choices[0].message.content.strip()
            logger.info(f"Raw LLM Response (Len: {len(content)}): {content[:100]}...")
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            total_tokens = getattr(usage, "total_tokens", None) if usage else None

            prompt_source = "provider"
            completion_source = "provider"
            if prompt_tokens is None:
                prompt_tokens = est_prompt_tokens
                prompt_source = "estimated"
            if completion_tokens is None:
                completion_tokens = self._estimate_tokens(content)
                completion_source = "estimated"
            if total_tokens is None:
                total_tokens = int(prompt_tokens) + int(completion_tokens)

            tok_per_sec = round((float(completion_tokens) / max(duration_ms / 1000.0, 0.001)), 2)
            logger.info(
                "OpenRouter Metrics | ReqId: %s | Model: %s | DurationMs: %d | PromptTokens: %s (%s) | CompletionTokens: %s (%s) | TotalTokens: %s | OutChars: %d | TokPerSec: %.2f",
                req_id,
                self.model,
                duration_ms,
                prompt_tokens,
                prompt_source,
                completion_tokens,
                completion_source,
                total_tokens,
                len(content),
                tok_per_sec,
            )
            
            # Use specialized parser
            data = extract_and_parse_json(content, strict=True)
            if not data:
                logger.warning("Could not parse JSON intent from OpenRouter.")
                try:
                    prompt_snapshot = "\n".join(
                        [f"{m.get('role')}: {m.get('content')}" for m in messages if isinstance(m, dict)]
                    )
                    write_contract_violation(
                        provider="openrouter",
                        model=self.model,
                        contract_name="agent_intent_v1",
                        prompt=prompt_snapshot,
                        raw_response={"content": content},
                        error_text="Failed to fulfill AgentIntent contract: Invalid JSON.",
                        attempt=1,
                        max_attempts=1,
                    )
                except Exception:
                    pass
                raise ProviderContractError("Failed to fulfill AgentIntent contract: Invalid JSON.")

            normalized_plan = self._normalize_plan_field(data.get("plan", []))
            state_summary = data.get("state_summary", {})
            if not isinstance(state_summary, dict):
                state_summary = {}

            params = data.get("params")
            attachments = data.get("attachments")
            if not attachments and isinstance(params, dict):
                attachments = params.get("attachments")
            normalized_attachments: Optional[List[str]] = None
            if isinstance(attachments, str) and attachments.strip():
                normalized_attachments = [attachments.strip()]
            elif isinstance(attachments, list):
                cleaned = [str(x).strip() for x in attachments if str(x).strip()]
                normalized_attachments = cleaned or None

            task_label = data.get("task_label")
            if task_label is not None:
                task_label = str(task_label)

            logger.info(
                "OpenRouter parsed intent | syntax_valid=true action_candidate=%s",
                str(data.get("action", "") or "").strip(),
            )
            return AgentIntent(
                thought=str(data.get("thought", "") or ""),
                plan=normalized_plan,
                state_summary=state_summary,
                action=str(data.get("action", "") or "").strip(),
                params=params if isinstance(params, dict) else {},
                task_label=task_label,
                response_text=str(data.get("response_text", data.get("reply", "")) or ""),
                attachments=normalized_attachments
            )

        except openai.AuthenticationError as e:
            duration_ms = int((time.perf_counter() - request_started_at) * 1000)
            logger.error("OpenRouter Auth Error | ReqId: %s | DurationMs: %d | Error: %s", req_id, duration_ms, e)
            raise ProviderAuthError(str(e), provider="openrouter")
        except openai.RateLimitError as e:
            duration_ms = int((time.perf_counter() - request_started_at) * 1000)
            # OpenRouter often returns 402 as a generic exception but sometimes rate limit
            logger.warning("OpenRouter Rate Limit | ReqId: %s | DurationMs: %d | Error: %s", req_id, duration_ms, e)
            raise ProviderRateLimitError(str(e), provider="openrouter")
        except openai.APIStatusError as e:
            duration_ms = int((time.perf_counter() - request_started_at) * 1000)
            if e.status_code == 402 or "can only afford" in str(e).lower():
                logger.error("OpenRouter Quota Exceeded | ReqId: %s | DurationMs: %d | Error: %s", req_id, duration_ms, e)
                raise ProviderQuotaError(str(e), provider="openrouter")
            logger.error("OpenRouter API Error | ReqId: %s | DurationMs: %d | Status: %s | Error: %s", req_id, duration_ms, e.status_code, e)
            raise e
        except Exception as e:
            duration_ms = int((time.perf_counter() - request_started_at) * 1000)
            logger.error("OpenRouter Error | ReqId: %s | DurationMs: %d | Error: %s", req_id, duration_ms, e)
            raise e

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        # Fast approximation for local telemetry when provider usage is unavailable.
        value = str(text or "")
        if not value:
            return 0
        return max(1, len(value) // 4)

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

    # JSON extraction logic moved to .parser.extract_and_parse_json

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """
        Directly analyzes an image using OpenRouter.
        """
        logger.info(f"Vision Request: Image={image_path} | Model={self.model}")
        if not os.path.exists(image_path):
            logger.error(f"Vision File Not Found: {image_path}")
            return f"Error: File not found: {image_path}"
            
        try:
            import base64
            import mimetypes
            
            mime_type, _ = mimetypes.guess_type(image_path)
            with open(image_path, "rb") as f:
                encoded_image = base64.b64encode(f.read()).decode('utf-8')
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type or 'image/png'};base64,{encoded_image}"
                            }
                        }
                    ]
                }
            ]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.vision_max_tokens,
                timeout=60.0
            )

            if response.choices and response.choices[0].message.content:
                return response.choices[0].message.content.strip()
            return response.choices[0].message.content.strip() if response.choices else "ERROR_EMPTY_VISION_RESPONSE"
        except Exception as e:
            logger.error(f"OpenRouter Vision Error: {e}")
            raise e

    def generate_text(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        """Generates plain text using OpenRouter."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=kwargs.get("max_tokens", 512)
            )
            return response.choices[0].message.content.strip() if response.choices else "ERROR_EMPTY_RESPONSE"
        except Exception as e:
            logger.error(f"OpenRouter generate_text error: {e}")
            raise e
