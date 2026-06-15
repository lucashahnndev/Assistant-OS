import os
import json
import logging
import re
import hashlib
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider, ProviderContractError
from server.core.secret_manager import resolve_secret_ref
from utils.logging_config import get_logger
from utils.contract_artifacts import write_contract_violation
from .parser import extract_and_parse_json

logger = get_logger("GeminiDriver")

class GeminiProvider(ILLMProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if not config:
            raise ValueError("GeminiProvider requires explicit pool configuration.")
        self.api_key = resolve_secret_ref(config.get("secret_ref"))
        self.model_name = config.get("model", "gemini-2.0-flash")
        
        self.max_tokens = int(config.get("max_tokens", 4096))
        # The new SDK takes http_options in the Client constructor.
        # Note: http_options['timeout'] expects MILLISECONDS.
        timeout_sec = int(config.get("timeout", 60))
        self.client = genai.Client(api_key=self.api_key, http_options={'timeout': timeout_sec * 1000})

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
    def _preview(value: Any, limit: int = 800) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return text[:limit] + "...<truncated>"

    @staticmethod
    def _parse_json_object_strict(raw_text: str) -> Dict[str, Any]:
        """
        Strict parser for structured output.
        No auto-repair and no heuristic field adaptation here.
        """
        text = str(raw_text or "").strip()
        if not text:
            raise ILLMProvider.contract_error(
                "Gemini structured output is empty.",
                provider_used="gemini",
                error_stage="provider",
                error_type="provider_exception",
                error_reason="empty_output",
                raw_response=raw_text,
                provider_parse_status="empty_output",
                provider_fallback_reason="provider_empty_output",
                provider_schema_mode="structured_json",
                provider_contract_mode="structured",
                extra={"diagnostic_source": "gemini"},
            )

        # Accept fenced JSON only when fence fully wraps the payload.
        if text.startswith("```"):
            match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                raise ILLMProvider.contract_error(
                    "Gemini structured output fence is malformed.",
                    provider_used="gemini",
                    error_stage="provider",
                    error_type="provider_contract_error",
                    error_reason="invalid_schema",
                    raw_response=raw_text,
                    provider_parse_status="invalid_schema",
                    provider_fallback_reason="provider_schema_error",
                    provider_schema_mode="structured_json",
                    provider_contract_mode="structured",
                    extra={"diagnostic_source": "gemini"},
                )
            text = match.group(1).strip()

        try:
            payload = json.loads(text)
        except Exception as exc:
            raise ILLMProvider.contract_error(
                f"Gemini structured output is not valid JSON: {exc}",
                provider_used="gemini",
                error_stage="provider",
                error_type="provider_exception",
                error_reason="invalid_json",
                raw_response=raw_text,
                provider_parse_status="invalid_json",
                provider_fallback_reason="provider_parse_error",
                provider_schema_mode="structured_json",
                provider_contract_mode="structured",
                extra={"diagnostic_source": "gemini"},
            ) from exc
        if not isinstance(payload, dict):
            raise ILLMProvider.contract_error(
                "Gemini structured output must be a JSON object.",
                provider_used="gemini",
                error_stage="provider",
                error_type="provider_contract_error",
                error_reason="invalid_schema",
                raw_response=raw_text,
                provider_parse_status="invalid_schema",
                provider_fallback_reason="provider_schema_error",
                provider_schema_mode="structured_json",
                provider_contract_mode="structured",
                extra={"diagnostic_source": "gemini"},
            )
        return payload

    @staticmethod
    def _safe_action_hint(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        try:
            action = data.get("action")
            return str(action or "").strip()
        except Exception:
            return ""

    def _emit_contract_artifact(
        self,
        *,
        contract: str,
        prompt: str,
        raw_response: Any,
        error: Exception,
        attempt: int,
        max_attempts: int,
        parsed_action: str = "",
        expected_action: str = "",
        extra: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        try:
            write_contract_violation(
                provider="gemini",
                model=self.model_name,
                contract_name=str(contract or ""),
                prompt=str(prompt or ""),
                raw_response=raw_response,
                error_text=str(error),
                attempt=attempt,
                max_attempts=max_attempts,
                session_id=str(kwargs.get("session_id") or ""),
                work_id=str(kwargs.get("work_id") or ""),
                trace_id=str(kwargs.get("trace_id") or ""),
                step_id=str(kwargs.get("step_id") or ""),
                parsed_action=parsed_action,
                expected_action=expected_action,
                extra=extra or {},
            )
        except Exception as artifact_err:
            logger.warning("Gemini artifact logger failed: %s", artifact_err)

    @staticmethod
    def _artifact_trace_ctx(kwargs: Dict[str, Any]) -> Dict[str, str]:
        return {
            "session_id": str(kwargs.get("session_id") or ""),
            "work_id": str(kwargs.get("work_id") or ""),
            "trace_id": str(kwargs.get("trace_id") or ""),
            "step_id": str(kwargs.get("step_id") or ""),
        }

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] | None = None, **kwargs) -> AgentIntent:
        system_instruction, contents = self.build_gemini_payload(
            history=history or [],
            user_input=user_input,
            system_prompt=system_prompt,
        )

        # Structured output prompt
        try:
            # We use GenerateContentConfig for the newer SDK
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                temperature=0.2, # Lower temperature for more consistent JSON
                max_output_tokens=kwargs.get("max_tokens", self.max_tokens)
            )

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )

            if not response.text:
                logger.error("Gemini returned an empty response.")
                raise ILLMProvider.contract_error(
                    "Gemini returned an empty response.",
                    provider_used="gemini",
                    error_stage="provider",
                    error_type="provider_exception",
                    error_reason="empty_output",
                    raw_response=response,
                    provider_parse_status="empty_output",
                    provider_fallback_reason="provider_empty_output",
                    provider_schema_mode="intent_json",
                    provider_contract_mode="intent",
                    extra={"diagnostic_source": "gemini"},
                )

            content = response.text.strip()
            
            # Use specialized parser
            data = extract_and_parse_json(content)
            
            if not data:
                logger.error("Failed to extract valid JSON from Gemini response.")
                raise ILLMProvider.contract_error(
                    "Failed to fulfill AgentIntent contract: Invalid JSON.",
                    provider_used="gemini",
                    error_stage="provider",
                    error_type="provider_exception",
                    error_reason="invalid_json",
                    raw_response=content,
                    provider_parse_status="invalid_json",
                    provider_fallback_reason="provider_parse_error",
                    provider_schema_mode="intent_json",
                    provider_contract_mode="intent",
                    extra={"diagnostic_source": "gemini"},
                )

            attachments = data.get("attachments")
            if not attachments and isinstance(data.get("params"), dict):
                attachments = data.get("params", {}).get("attachments")
                
            response_text = self._normalize_response_text(
                data.get("response_text", data.get("reply", "")),
                fallback="",
            )
            action = str(data.get("action", "") or "").strip()
            if not action:
                raise ILLMProvider.contract_error(
                    "Gemini intent missing action.",
                    provider_used="gemini",
                    error_stage="provider",
                    error_type="provider_contract_error",
                    error_reason="missing_action",
                    raw_response=data,
                    provider_parse_status="missing_action",
                    provider_fallback_reason="provider_contract_error",
                    provider_schema_mode="intent_json",
                    provider_contract_mode="intent",
                    extra={"diagnostic_source": "gemini"},
                )
            if action == "reply" and not response_text.strip():
                raise ILLMProvider.contract_error(
                    "Gemini reply missing response_text.",
                    provider_used="gemini",
                    error_stage="provider",
                    error_type="provider_contract_error",
                    error_reason="missing_response_text",
                    raw_response=data,
                    provider_parse_status="missing_response_text",
                    provider_fallback_reason="provider_contract_error",
                    provider_schema_mode="intent_json",
                    provider_contract_mode="intent",
                    extra={"diagnostic_source": "gemini"},
                )
            allowed_actions = kwargs.get("allowed_actions")
            if isinstance(allowed_actions, (list, tuple, set)):
                allowed = {str(item).strip() for item in allowed_actions if str(item or "").strip()}
                if allowed and action not in allowed:
                    raise ILLMProvider.contract_error(
                        f"Gemini returned unsupported action: {action}.",
                        provider_used="gemini",
                        error_stage="provider",
                        error_type="provider_contract_error",
                        error_reason="unsupported_action",
                        raw_response=data,
                        provider_parse_status="unsupported_action",
                        provider_fallback_reason="provider_contract_error",
                        provider_schema_mode="intent_json",
                        provider_contract_mode="intent",
                        extra={"diagnostic_source": "gemini"},
                    )

            # Ensure 'thought' is never truly empty to satisfy validation
            thought = str(data.get("thought", "")).strip()
            if not thought:
                thought = "Gemini processing turn."

            return AgentIntent(
                thought=thought,
                plan=data.get("plan", []),
                action=action,
                params=data.get("params", {}),
                state_summary=data.get("state_summary", {}),
                response_text=response_text,
                attachments=attachments
            )

        except Exception as e:
            logger.error(f"Gemini Error: {e}")
            raise e

    def generate_text(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        """Generates plain text using the Flash model."""
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
                max_output_tokens=kwargs.get("max_tokens", self.max_tokens)
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[prompt],
                config=config
            )
            content = str(response.text or "").strip()
            if not content:
                raise ILLMProvider.contract_text_empty_error(
                    "Gemini generate_text returned empty output.",
                    provider_used="gemini",
                    raw_response="",
                    provider_schema_mode="text",
                    provider_contract_mode="text",
                    diagnostic_source="gemini",
                )
            return content
        except Exception as e:
            logger.error(f"Gemini generate_text error: {e}")
            raise e

    def generate_structured(self, prompt: str, system_prompt: str = "", **kwargs) -> Dict[str, Any]:
        """
        Structured generation in the provider layer.
        Uses Gemini JSON mode and returns normalized contract payload.
        """
        try:
            contract = str(kwargs.get("contract", "") or "").strip().lower()
            max_attempts = int(kwargs.get("contract_max_attempts", 3) or 3)
            max_attempts = max(1, min(max_attempts, 5))
            last_error: Optional[Exception] = None

            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.0,
                max_output_tokens=kwargs.get("max_tokens", self.max_tokens),
            )
            for attempt in range(1, max_attempts + 1):
                data: Dict[str, Any] = {}
                attempt_prompt = prompt
                if attempt > 1:
                    attempt_prompt = (
                        f"{prompt}\n\n"
                        "IMPORTANT: Return ONLY valid JSON object for the requested contract. "
                        "No markdown, no comments, no trailing text."
                    )
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[attempt_prompt],
                    config=config,
                )
                content = (response.text or "").strip()
                logger.info(
                    "Gemini structured raw contract=%s attempt=%s/%s chars=%s preview=%s",
                    contract,
                    attempt,
                    max_attempts,
                    len(content),
                    self._preview(content),
                )
                try:
                    data = self._parse_json_object_strict(content)
                    if contract == "browser_planner_action_v1":
                        normalized = self._normalize_browser_planner_contract(data, strict=True)
                        logger.info(
                            "Gemini structured normalized contract=%s action=%s step_status=%s",
                            contract,
                            str(normalized.get("action") or ""),
                            str(normalized.get("step_status") or ""),
                        )
                        return normalized
                    return data
                except Exception as exc:
                    last_error = exc if isinstance(exc, Exception) else Exception(str(exc))
                    parsed_action = ""
                    try:
                        parsed_action = self._safe_action_hint(data if "data" in locals() else {})
                    except Exception:
                        parsed_action = ""
                    self._emit_contract_artifact(
                        contract=contract,
                        prompt=attempt_prompt,
                        raw_response=content,
                        error=last_error,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        parsed_action=parsed_action,
                        expected_action="browser_action" if contract == "browser_planner_action_v1" else "",
                        extra={
                            "system_prompt_fingerprint": hashlib.sha256(
                                str(system_prompt or "").encode("utf-8")
                            ).hexdigest(),
                            "stage": "generate_structured_attempt",
                        },
                        **self._artifact_trace_ctx(kwargs),
                    )
                    logger.warning(
                        "Gemini structured contract violation contract=%s attempt=%s/%s error=%s",
                        contract,
                        attempt,
                        max_attempts,
                        str(last_error),
                    )
                    continue
            raise ILLMProvider.contract_error(
                f"Gemini failed structured contract after {max_attempts} attempts: {last_error}",
                provider_used="gemini",
                error_stage="provider",
                error_type="provider_contract_error",
                error_reason="invalid_schema" if "schema" in str(last_error or "").lower() else "invalid_json",
                raw_response=last_error,
                provider_parse_status="invalid_schema" if "schema" in str(last_error or "").lower() else "invalid_json",
                provider_fallback_reason="provider_schema_error" if "schema" in str(last_error or "").lower() else "provider_parse_error",
                provider_schema_mode="structured_json",
                provider_contract_mode="structured",
                extra={"diagnostic_source": "gemini"},
            )
        except Exception as e:
            logger.error(f"Gemini generate_structured error: {e}")
            raise e

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """
        Directly analyzes an image using Gemini.
        """
        if not os.path.exists(image_path):
            return f"Error: Arquivo não encontrado: {image_path}"
            
        try:
            import mimetypes
            mime_type, _ = mimetypes.guess_type(image_path)
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            
            content = [
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/png")
            ]
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=content,
                config=types.GenerateContentConfig(temperature=0.4)
            )
            
            return response.text or "ERROR_EMPTY_VISION_RESPONSE"
        except Exception as e:
            logger.error(f"Gemini Vision Error: {e}")
            raise e

    def analyze_image_structured(self, image_path: str, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Structured vision output in provider layer.
        """
        if not os.path.exists(image_path):
            raise ILLMProvider.contract_error(
                f"Image file not found: {image_path}",
                provider_used="gemini",
                error_stage="provider",
                error_type="provider_contract_error",
                error_reason="missing_attachment",
                raw_response=image_path,
                provider_parse_status="unknown_error",
                provider_fallback_reason="provider_contract_error",
                provider_schema_mode="structured_json",
                provider_contract_mode="structured",
                extra={"diagnostic_source": "gemini"},
            )
        try:
            artifact_emitted = False
            import mimetypes
            mime_type, _ = mimetypes.guess_type(image_path)
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            content = [
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/png"),
            ]
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
                max_output_tokens=kwargs.get("max_tokens", self.max_tokens),
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=content,
                config=config,
            )
            raw_text = (response.text or "").strip()
            logger.info(
                "Gemini vision structured raw contract=%s chars=%s preview=%s",
                str(kwargs.get("contract", "") or ""),
                len(raw_text),
                self._preview(raw_text),
            )
            payload = extract_and_parse_json(raw_text)
            if not isinstance(payload, dict) or not payload:
                err = ILLMProvider.contract_error(
                    "Gemini vision structured output invalid.",
                    provider_used="gemini",
                    error_stage="provider",
                    error_type="provider_exception",
                    error_reason="invalid_json",
                    raw_response=raw_text,
                    provider_parse_status="invalid_json",
                    provider_fallback_reason="provider_parse_error",
                    provider_schema_mode="structured_json_vision",
                    provider_contract_mode="structured",
                    extra={"diagnostic_source": "gemini"},
                )
                self._emit_contract_artifact(
                    contract=str(kwargs.get("contract", "") or ""),
                    prompt=prompt,
                    raw_response=raw_text,
                    error=err,
                    attempt=1,
                    max_attempts=1,
                    expected_action="vision_contract",
                    extra={"stage": "analyze_image_structured"},
                    **self._artifact_trace_ctx(kwargs),
                )
                artifact_emitted = True
                raise err

            contract = str(kwargs.get("contract", "") or "").strip().lower()
            if contract == "vision_locator_v1":
                return self._normalize_vision_locator_contract(
                    payload, fallback_label=str(kwargs.get("label") or "")
                )
            if contract == "vision_analysis_v1":
                return self._normalize_vision_analysis_contract(payload)
            return payload
        except Exception as e:
            if not locals().get("artifact_emitted", False):
                self._emit_contract_artifact(
                    contract=str(kwargs.get("contract", "") or ""),
                    prompt=prompt,
                    raw_response="",
                    error=e if isinstance(e, Exception) else Exception(str(e)),
                    attempt=1,
                    max_attempts=1,
                    expected_action="vision_contract",
                    extra={"stage": "analyze_image_structured_exception"},
                    **self._artifact_trace_ctx(kwargs),
                )
            logger.error(f"Gemini analyze_image_structured error: {e}")
            raise e
