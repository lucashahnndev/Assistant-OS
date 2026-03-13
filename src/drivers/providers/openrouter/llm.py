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
from .parser import extract_and_parse_json, repair_json

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

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] | None = None, **kwargs) -> AgentIntent:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})

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
            # We remove 'tools' and 'tool_choice' to support generic models
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
            data = extract_and_parse_json(content)
            if not data:
                logger.warning("Could not parse JSON intent from OpenRouter.")
                raise ProviderContractError("Failed to fulfill AgentIntent contract: Invalid JSON.")

            # VALIDATION & EXTRACTION
            thought = str(data.get("thought", "") or "").strip() or "Reasoning omitted by model."
            action = str(data.get("action", "") or "").strip()
            params = data.get("params", {})
            response_text_raw = data.get("response_text", "")
            if isinstance(response_text_raw, str):
                response_text = response_text_raw
            elif response_text_raw is None:
                response_text = ""
            elif isinstance(response_text_raw, dict):
                candidate = (
                    response_text_raw.get("text")
                    or response_text_raw.get("response")
                    or response_text_raw.get("message")
                )
                response_text = str(candidate) if candidate is not None else json.dumps(response_text_raw, ensure_ascii=False)
            elif isinstance(response_text_raw, list):
                response_text = json.dumps(response_text_raw, ensure_ascii=False)
            else:
                response_text = str(response_text_raw)

            if not action:
                action = "reply"
            if action == "reply" and not response_text:
                response_text = thought
            
            normalized_plan = self._normalize_plan_field(data.get("plan", []))
            state_summary = data.get("state_summary", {})
            if not isinstance(state_summary, dict):
                state_summary = {}

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

            return AgentIntent(
                thought=thought,
                plan=normalized_plan,
                state_summary=state_summary,
                action=action,
                params=params if isinstance(params, dict) else {},
                task_label=task_label,
                response_text=response_text,
                attachments=normalized_attachments
            )

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

            def _request_with_tokens(max_tokens: int):
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    timeout=60.0
                )

            try:
                response = _request_with_tokens(self.vision_max_tokens)
            except Exception as first_exc:
                # Credit-aware retry for OpenRouter 402 messages:
                # "...requested up to X tokens, but can only afford Y..."
                err_text = str(first_exc)
                affordable_match = re.search(r"can only afford\s+(\d+)", err_text, flags=re.IGNORECASE)
                if affordable_match:
                    affordable = max(64, int(affordable_match.group(1)))
                    retry_tokens = min(self.vision_max_tokens, affordable)
                    if retry_tokens < self.vision_max_tokens:
                        logger.warning(
                            "Vision request exceeded credits. Retrying with lower max_tokens=%s (affordable=%s).",
                            retry_tokens,
                            affordable,
                        )
                        response = _request_with_tokens(retry_tokens)
                    else:
                        raise
                else:
                    raise

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
