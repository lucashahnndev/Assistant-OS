from abc import ABC, abstractmethod
import json
import re
import math
from typing import Dict, Any, List, Optional
from core.intent import AgentIntent

class ProviderContractError(Exception):
    """
    Exception raised when a provider fails to fulfill its contract
    (e.g., persistent malformed JSON after repair attempts).
    Triggers the Kernel's fallback mechanism.
    """
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

class ILLMProvider(ABC):
    """
    Interface for LLM Providers (OpenAI, Ollama, etc.).
    Responsible for connecting to the model and parsing the response into an AgentIntent.
    """

    RAW_PREVIEW_LIMIT = 1200
    _REDACTION_PATTERNS = (
        (re.compile(r'(?i)("?(?:api[_-]?key|secret|token|password|authorization)"?\s*[:=]\s*")([^"\n]{4,})(")'), r'\1<redacted>\3'),
        (re.compile(r'(?i)(authorization\s*:\s*bearer\s+)([A-Za-z0-9._\-+/=]+)'), r'\1<redacted>'),
        (re.compile(r'(?i)(secret_ref\s*[:=]\s*)([^\s,"\'}]+)'), r'\1<redacted>'),
    )
    _ALLOWED_ERROR_STAGES = {"provider", "llm_manager", "resolver", "gatekeeper", "orchestrator", "recovery", "sanitizer", "session_pipeline"}
    _ALLOWED_PARSE_STATUSES = {
        "ok",
        "empty_output",
        "invalid_json",
        "invalid_schema",
        "missing_action",
        "missing_response_text",
        "unsupported_action",
        "provider_exception",
        "timeout",
        "unknown_error",
    }
    _ALLOWED_FALLBACK_REASONS = {
        "none",
        "provider_parse_error",
        "provider_schema_error",
        "provider_empty_output",
        "provider_timeout",
        "provider_exception",
        "provider_contract_error",
        "all_providers_failed",
        "fallback_provider_used",
    }

    @abstractmethod
    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] | None = None, **kwargs) -> AgentIntent:
        """
        Generates an structured intent from the user input and context.
        
        Args:
            user_input (str): The latest message from the user.
            history (List[Dict[str, str]]): Conversation history.
            system_prompt (str): The core instructions for the agent.
            attachments (List[str]): Paths to files (images) attached to the message.

        Returns:
            AgentIntent: The structured intent (thought, action, params).
        """
        pass

    @abstractmethod
    def generate_text(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        """
        Generates a plain text response from a prompt. 
        Used for internal utilities like summarization and log compression.
        """
        pass

    @classmethod
    def _sanitize_raw_text(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                text = str(value)
        redacted = text
        for pattern, replacement in cls._REDACTION_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    @classmethod
    def build_raw_preview(cls, value: Any, limit: Optional[int] = None) -> Dict[str, Any]:
        limit_value = int(limit or cls.RAW_PREVIEW_LIMIT)
        limit_value = max(64, min(limit_value, 4096))
        text = cls._sanitize_raw_text(value)
        chars = len(text)
        truncated = chars > limit_value
        preview = text[:limit_value]
        return {
            "raw_preview": preview,
            "raw_preview_truncated": truncated,
            "raw_preview_chars": chars,
        }

    @classmethod
    def normalize_provider_parse_status(cls, value: Optional[str], *, raw_empty: bool = False, error_reason: str = "") -> str:
        candidate = str(value or "").strip().lower()
        if candidate in cls._ALLOWED_PARSE_STATUSES:
            return candidate
        if raw_empty:
            return "empty_output"
        reason = str(error_reason or "").strip().lower()
        if "timeout" in reason:
            return "timeout"
        if "invalid json" in reason or "json" in reason or "parse" in reason:
            return "invalid_json"
        if "missing response_text" in reason:
            return "missing_response_text"
        if "missing action" in reason or "invalid action" in reason:
            return "missing_action"
        if "schema" in reason:
            return "invalid_schema"
        if "unsupported" in reason:
            return "unsupported_action"
        if "contract" in reason:
            return "provider_exception"
        return "unknown_error"

    @classmethod
    def normalize_provider_fallback_reason(cls, value: Optional[str], *, parse_status: str = "", error_reason: str = "") -> str:
        candidate = str(value or "").strip().lower()
        if candidate in cls._ALLOWED_FALLBACK_REASONS and candidate != "none":
            return candidate
        status = str(parse_status or "").strip().lower()
        if status == "empty_output":
            return "provider_empty_output"
        if status in {"invalid_json", "invalid_schema", "missing_action", "missing_response_text", "unsupported_action"}:
            return "provider_contract_error"
        if status == "timeout":
            return "provider_timeout"
        if status == "provider_exception":
            return "provider_exception"
        reason = str(error_reason or "").strip().lower()
        if "timeout" in reason:
            return "provider_timeout"
        if "schema" in reason:
            return "provider_schema_error"
        if "json" in reason or "parse" in reason:
            return "provider_parse_error"
        if "contract" in reason:
            return "provider_contract_error"
        if reason:
            return "provider_exception"
        return "none"

    @classmethod
    def build_contract_diagnostics(
        cls,
        *,
        provider_used: str,
        error_stage: str,
        error_type: str,
        error_reason: str,
        raw_response: Any = None,
        provider_parse_status: str = "",
        provider_fallback_reason: str = "",
        provider_schema_mode: str = "",
        provider_contract_mode: str = "intent",
        semantic_authority: bool = False,
        diagnostic_source: str = "provider",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        preview = cls.build_raw_preview(raw_response)
        parse_status = cls.normalize_provider_parse_status(
            provider_parse_status,
            raw_empty=not bool(str(raw_response or "").strip()),
            error_reason=error_reason,
        )
        fallback_reason = cls.normalize_provider_fallback_reason(
            provider_fallback_reason,
            parse_status=parse_status,
            error_reason=error_reason,
        )
        payload: Dict[str, Any] = {
            "diagnostic_source": diagnostic_source,
            "error_stage": error_stage,
            "error_type": error_type,
            "error_reason": error_reason,
            "provider_used": provider_used,
            "provider_parse_status": parse_status,
            "provider_fallback_reason": fallback_reason,
            "provider_schema_mode": provider_schema_mode,
            "provider_contract_mode": provider_contract_mode,
            "semantic_authority": semantic_authority,
        }
        payload.update(preview)
        if extra:
            for key, value in extra.items():
                if value not in (None, "", [], {}):
                    payload[key] = value
        return payload

    @classmethod
    def contract_error(
        cls,
        message: str,
        *,
        provider_used: str,
        error_stage: str,
        error_type: str,
        error_reason: str,
        raw_response: Any = None,
        provider_parse_status: str = "",
        provider_fallback_reason: str = "",
        provider_schema_mode: str = "",
        provider_contract_mode: str = "intent",
        semantic_authority: bool = False,
        diagnostic_source: str = "provider",
        extra: Optional[Dict[str, Any]] = None,
    ) -> ProviderContractError:
        return ProviderContractError(
            message,
            details=cls.build_contract_diagnostics(
                provider_used=provider_used,
                error_stage=error_stage,
                error_type=error_type,
                error_reason=error_reason,
                raw_response=raw_response,
                provider_parse_status=provider_parse_status,
                provider_fallback_reason=provider_fallback_reason,
                provider_schema_mode=provider_schema_mode,
                provider_contract_mode=provider_contract_mode,
                semantic_authority=semantic_authority,
                diagnostic_source=diagnostic_source,
                extra=extra,
            ),
        )

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    @classmethod
    def _normalize_browser_action_fields(cls, action: Any, args: Any, strict: bool = False) -> Dict[str, Any]:
        allowed_actions = {
            "navigate",
            "click",
            "click_visual",
            "type",
            "scroll",
            "vision",
            "wait",
            "answer",
            "press_key",
            "action_batch",
        }

        action_s = str(action or "wait").strip().lower()
        if action_s not in allowed_actions:
            if strict:
                raise ProviderContractError(f"Invalid browser action: {action_s}")
            action_s = "wait"
        args_d = args if isinstance(args, dict) else {}

        if action_s == "navigate":
            url = str(args_d.get("url") or "").strip()
            if not url:
                if strict:
                    raise ProviderContractError("navigate action requires non-empty args.url")
                return {"action": "wait", "args": {"seconds": 1}}
            return {"action": action_s, "args": {"url": url}}

        if action_s == "click":
            node_id = str(args_d.get("id") or "").strip()
            if not node_id:
                if strict:
                    raise ProviderContractError("click action requires non-empty args.id")
                return {"action": "wait", "args": {"seconds": 1}}
            return {"action": action_s, "args": {"id": node_id}}

        if action_s == "click_visual":
            x = cls._to_float(args_d.get("x"), default=-1.0)
            y = cls._to_float(args_d.get("y"), default=-1.0)
            # Tolerant coercion for common model mistakes:
            # - normalized 0..1 scale
            # - small overshoot (e.g., -20 / 1015)
            if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                x *= 1000.0
                y *= 1000.0

            if not (math.isfinite(x) and math.isfinite(y)):
                if strict:
                    raise ProviderContractError("click_visual action requires finite x/y coordinates")
                return {"action": "wait", "args": {"seconds": 1}}

            if -100.0 <= x <= 1100.0 and -100.0 <= y <= 1100.0:
                x = max(0.0, min(1000.0, x))
                y = max(0.0, min(1000.0, y))
            elif x < 0 or x > 1000 or y < 0 or y > 1000:
                if strict:
                    raise ProviderContractError("click_visual action requires 0<=x<=1000 and 0<=y<=1000")
                return {"action": "wait", "args": {"seconds": 1}}
            return {"action": action_s, "args": {"x": x, "y": y}}

        if action_s == "type":
            node_id = str(args_d.get("id") or "").strip()
            text = str(args_d.get("text") or "")
            if not node_id:
                if strict:
                    raise ProviderContractError("type action requires non-empty args.id")
                return {"action": "wait", "args": {"seconds": 1}}
            return {
                "action": action_s,
                "args": {
                    "id": node_id,
                    "text": text,
                    "press_enter": bool(args_d.get("press_enter", False)),
                },
            }

        if action_s == "scroll":
            direction = str(args_d.get("direction") or "down").strip().lower()
            if direction not in ("down", "up"):
                direction = "down"
            return {"action": action_s, "args": {"direction": direction}}

        if action_s == "vision":
            reason = str(args_d.get("reason") or "").strip()
            return {"action": action_s, "args": {"reason": reason}}

        if action_s == "wait":
            seconds = cls._to_float(args_d.get("seconds"), default=1.0)
            seconds = max(0.1, min(seconds, 8.0))
            return {"action": action_s, "args": {"seconds": seconds}}

        if action_s == "answer":
            return {"action": action_s, "args": {"text": str(args_d.get("text") or "")}}

        if action_s == "press_key":
            return {"action": action_s, "args": {"key": str(args_d.get("key") or "Enter")}}

        # action_batch is normalized in _normalize_browser_planner_contract.
        return {"action": "wait", "args": {"seconds": 1}}

    @staticmethod
    def _normalize_browser_batch_policy(policy: Any) -> Dict[str, Any]:
        p = policy if isinstance(policy, dict) else {}
        max_steps = p.get("max_steps", 10)
        try:
            max_steps_i = int(max_steps)
        except Exception:
            max_steps_i = 10
        return {
            "stop_on_error": bool(p.get("stop_on_error", True)),
            "max_steps": max(1, min(max_steps_i, 10)),
        }

    @staticmethod
    def _normalize_browser_batch_steps(
        data: Dict[str, Any],
        args: Dict[str, Any],
        strict: bool = False,
    ) -> List[Dict[str, Any]]:
        candidates = data.get("steps")
        if not isinstance(candidates, list):
            candidates = args.get("steps")
        if not isinstance(candidates, list):
            candidates = data.get("actions")
        if not isinstance(candidates, list):
            candidates = data.get("commands")
        if not isinstance(candidates, list):
            if strict:
                raise ProviderContractError("action_batch requires list payload in steps/actions/commands")
            return []

        normalized: List[Dict[str, Any]] = []
        for raw_step in candidates[:10]:
            if not isinstance(raw_step, dict):
                if strict:
                    raise ProviderContractError("action_batch contains non-object step")
                continue
            step_action = raw_step.get("action")
            step_args = raw_step.get("args")
            step_args_d = step_args if isinstance(step_args, dict) else {}

            # Optional canonic target envelope support.
            target = raw_step.get("target")
            if isinstance(target, dict):
                by = str(target.get("by") or "").strip().lower()
                value = target.get("value")
                if by in ("id", "selector") and value is not None and not step_args_d.get("id"):
                    step_args_d["id"] = str(value)
                elif by == "coords" and isinstance(value, dict):
                    if "x" in value and "x" not in step_args_d:
                        step_args_d["x"] = value.get("x")
                    if "y" in value and "y" not in step_args_d:
                        step_args_d["y"] = value.get("y")

            one = ILLMProvider._normalize_browser_action_fields(step_action, step_args_d, strict=strict)
            if one.get("action") == "action_batch":
                if strict:
                    raise ProviderContractError("Nested action_batch is not allowed")
                continue
            normalized.append(one)
        return normalized

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        fenced = re.search(r"```(?:json|yaml|yml|md|markdown|toon)?\s*(.*?)\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            return fenced.group(1).strip()
        return raw

    @classmethod
    def _repair_common_json_issues(cls, text: str) -> str:
        raw = cls._strip_code_fences(text)
        if not raw:
            return ""

        # Normalize smart quotes
        raw = (
            raw.replace("“", "\"")
            .replace("”", "\"")
            .replace("’", "'")
            .replace("‘", "'")
        )

        # Remove trailing commas before object/array close
        raw = re.sub(r",(\s*[}\]])", r"\1", raw)

        # Repair a common malformed key pattern seen in model output:
        # "thought: ...",
        # into:
        # "thought": "...",
        def _fix_inline_key(m: re.Match) -> str:
            key = m.group(1).strip()
            value = m.group(2).strip().replace("\"", "\\\"")
            return f"\"{key}\": \"{value}\","

        raw = re.sub(
            r"\"(thought|step_status|action)\s*:\s*([^\"\n][^\n]*?)\",",
            _fix_inline_key,
            raw,
            flags=re.IGNORECASE,
        )
        return raw

    @staticmethod
    def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
        raw = ILLMProvider._repair_common_json_issues(text)
        if not raw:
            return None

        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        raw = raw[start:end + 1]

        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _extract_bool(text: str, key: str, default: bool = False) -> bool:
        m = re.search(rf"{re.escape(key)}\s*[:=]\s*(true|false)", text, flags=re.IGNORECASE)
        if not m:
            return default
        return m.group(1).strip().lower() == "true"

    @staticmethod
    def _extract_number(text: str, key: str) -> Optional[float]:
        m = re.search(rf"{re.escape(key)}\s*[:=]\s*(-?\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
        if not m:
            return None
        try:
            return float(m.group(1))
        except Exception:
            return None

    @staticmethod
    def _extract_quoted_or_unquoted(text: str, key: str) -> Optional[str]:
        # key: "value"
        m = re.search(rf"{re.escape(key)}\s*[:=]\s*\"([^\"]*)\"", text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # key: 'value'
        m = re.search(rf"{re.escape(key)}\s*[:=]\s*'([^']*)'", text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # key: value (until line end/comma)
        m = re.search(rf"{re.escape(key)}\s*[:=]\s*([^\n,}}]+)", text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip().strip("\"'")
        return None

    @classmethod
    def _extract_browser_contract_heuristic(cls, text: str) -> Optional[Dict[str, Any]]:
        """
        Best-effort fallback for browser planner payloads when provider emits
        almost-JSON / YAML-like text.
        """
        raw = cls._strip_code_fences(text)
        if not raw:
            return None
        compact = raw.replace("\r", "")
        low = compact.lower()

        # Detect action robustly
        action = cls._extract_quoted_or_unquoted(compact, "action")
        if not action:
            for candidate in ("navigate", "click_visual", "click", "type", "scroll", "vision", "wait", "answer", "press_key", "action_batch"):
                if re.search(rf"\b{candidate}\b", low):
                    action = candidate
                    break
        if not action:
            return None
        action = str(action).strip().lower()

        thought = cls._extract_quoted_or_unquoted(compact, "thought") or ""
        step_status = (cls._extract_quoted_or_unquoted(compact, "step_status") or "in_progress").strip().lower()
        if step_status not in ("in_progress", "completed"):
            step_status = "in_progress"

        args: Dict[str, Any] = {}
        for key in ("id", "url", "text", "reason", "direction", "key"):
            v = cls._extract_quoted_or_unquoted(compact, key)
            if v:
                args[key] = v
        for key in ("x", "y", "seconds"):
            n = cls._extract_number(compact, key)
            if n is not None:
                args[key] = n
        if re.search(r"press[_\s-]*enter", low):
            args["press_enter"] = cls._extract_bool(compact, "press_enter", default=True)

        return {
            "thought": thought,
            "step_status": step_status,
            "action": action,
            "args": args,
            "response_text": "",
        }

    @staticmethod
    def _normalize_browser_planner_contract(data: Dict[str, Any], strict: bool = False) -> Dict[str, Any]:
        thought = data.get("thought", "")
        step_status = str(data.get("step_status", "in_progress") or "in_progress").lower()
        action = str(data.get("action", "") or "").strip().lower()
        args = data.get("args", {})
        response_text = data.get("response_text", "")

        if step_status not in ("in_progress", "completed"):
            if strict:
                raise ProviderContractError(f"Invalid step_status: {step_status}")
            step_status = "in_progress"
        if not isinstance(args, dict):
            if strict:
                raise ProviderContractError("args must be an object")
            args = {}
        if strict and not isinstance(thought, str):
            raise ProviderContractError("thought must be a string")

        # If provider omitted action but returned commands/steps/actions list,
        # force canonical batch mode.
        if not action:
            for key in ("steps", "actions", "commands"):
                if isinstance(data.get(key), list):
                    action = "action_batch"
                    break
        if not action:
            if strict:
                raise ProviderContractError("Missing required action")
            action = "wait"

        if action == "action_batch":
            steps = ILLMProvider._normalize_browser_batch_steps(data, args, strict=strict)
            if not steps:
                if strict:
                    raise ProviderContractError("action_batch requires at least one valid step")
                normalized = {"action": "wait", "args": {"seconds": 1}}
            else:
                normalized = {
                    "action": "action_batch",
                    "args": {
                        "steps": steps,
                        "policy": ILLMProvider._normalize_browser_batch_policy(
                            data.get("policy") if isinstance(data.get("policy"), dict) else args.get("policy")
                        ),
                    },
                }
        else:
            normalized = ILLMProvider._normalize_browser_action_fields(action, args, strict=strict)

        canonical = {
            "thought": thought if isinstance(thought, str) else str(thought),
            "step_status": step_status,
            "action": str(normalized.get("action") or "wait"),
            "args": normalized.get("args") if isinstance(normalized.get("args"), dict) else {},
            "response_text": response_text if isinstance(response_text, str) else str(response_text),
        }
        if strict:
            allowed_top = {"thought", "step_status", "action", "args", "response_text"}
            if set(canonical.keys()) != allowed_top:
                raise ProviderContractError("Canonical browser planner payload has unexpected shape")
        return canonical

    def generate_structured(self, prompt: str, system_prompt: str = "", **kwargs) -> Dict[str, Any]:
        """
        Driver-level structured generation contract.
        Core/capabilities must consume this instead of parsing raw provider text.
        """
        raw = self.generate_text(prompt=prompt, system_prompt=system_prompt, **kwargs)
        data = raw if isinstance(raw, dict) else self._extract_json_object(str(raw or ""))
        contract = str(kwargs.get("contract", "") or "").strip().lower()
        if not isinstance(data, dict) and contract == "browser_planner_action_v1":
            data = self._extract_browser_contract_heuristic(str(raw or ""))
        if not isinstance(data, dict):
            raise ProviderContractError("Structured contract failure: provider output is not valid JSON object.")
        if contract == "browser_planner_action_v1":
            return self._normalize_browser_planner_contract(data, strict=True)
        return data

    @staticmethod
    def _normalize_vision_analysis_contract(data: Dict[str, Any], fallback_text: str = "") -> Dict[str, Any]:
        summary = data.get("summary")
        if summary is None:
            summary = data.get("analysis")
        if summary is None:
            summary = data.get("response")
        if summary is None:
            summary = fallback_text

        findings = data.get("findings")
        if not isinstance(findings, list):
            findings = []

        return {
            "summary": str(summary or "").strip(),
            "findings": [str(x).strip() for x in findings if str(x).strip()],
            "safety_flags": data.get("safety_flags", []),
            "raw": data if isinstance(data, dict) else {},
        }

    @staticmethod
    def _normalize_vision_locator_contract(data: Dict[str, Any], fallback_label: str = "") -> Dict[str, Any]:
        label = str(data.get("label") or fallback_label or "target")
        found = bool(data.get("found", True))
        bbox = {
            "label": label,
            "confidence": float(data.get("confidence") or 0.0),
            "x": float(data.get("x") or 0.0),
            "y": float(data.get("y") or 0.0),
            "width": float(data.get("width") or 0.0),
            "height": float(data.get("height") or 0.0),
            "coordinate_space": str(data.get("coordinate_space") or "normalized_1000"),
        }
        if data.get("screen_id") is not None:
            try:
                bbox["screen_id"] = int(data.get("screen_id"))
            except Exception:
                pass
        return {
            "found": found,
            "bbox": bbox,
            "reason": str(data.get("reason") or ""),
            "raw": data if isinstance(data, dict) else {},
        }

    def analyze_image_structured(self, image_path: str, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Driver-level structured vision contract.
        """
        raw = self.analyze_image(image_path=image_path, prompt=prompt)
        data = raw if isinstance(raw, dict) else self._extract_json_object(str(raw or ""))
        if not isinstance(data, dict):
            raise ProviderContractError("Vision contract failure: provider output is not valid JSON object.")

        contract = str(kwargs.get("contract", "") or "").strip().lower()
        if contract == "vision_locator_v1":
            return self._normalize_vision_locator_contract(data, fallback_label=str(kwargs.get("label") or ""))
        if contract == "vision_analysis_v1":
            return self._normalize_vision_analysis_contract(data, fallback_text=str(raw or ""))
        return data

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """
        Directly analyzes an image without conversation history.
        Default implementation returns an error if not overridden.
        """
        return "Error: Este provedor de LLM não suporta análise direta de imagens (Visão)."
