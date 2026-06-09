from typing import List, Dict, Optional, Any
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider, ProviderContractError
from utils.plugin_loader import PluginLoader
from config import ConfigManager
from utils.contract_artifacts import write_contract_violation
import os
import sys
import logging

from utils.logging_config import get_logger

# Configure logging
logger = get_logger(__name__)

# Add src to python path if not present
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

class LLMManager:
    def __init__(self):
        self.config_manager = ConfigManager()
        self._last_router_meta: Dict[str, Any] = {}
        self.provider_health: Dict[str, Dict[str, Any]] = {}
        self._load_config()
        self._load_providers()

    def reload(self):
        """Reloads configuration and re-instantiates all providers."""
        logger.info("Hot Reloading LLMManager...")
        self._load_config()
        self._load_providers()
        logger.info("LLMManager Reloaded with new pool.")

    def _load_config(self):
        cfg = self.config_manager.get("cortex", {})
        self.chat_config = cfg.get("chat", [])
        self.vision_config = cfg.get("vision", [])

    def _load_providers(self):
        self.chat_pool = []
        self.vision_pool = []
        
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        providers_root = os.path.join(root_dir, 'drivers', 'providers')
        
        loaded_classes = {}
        if os.path.exists(providers_root):
            for entry in os.listdir(providers_root):
                p_dir = os.path.join(providers_root, entry)
                if os.path.isdir(p_dir):
                    # Load from subfolder (e.g. drivers/providers/gemini)
                    res = PluginLoader.load_plugins(p_dir, ILLMProvider)
                    # Use directory name (entry) as the key instead of module name (usually 'llm')
                    for cls in res.values():
                        loaded_classes[entry] = cls
        
        if not loaded_classes:
            logger.warning("No LLM Providers found!")
            return

        def normalize_name(name):
            key = name.lower().replace("_driver", "").replace("provider", "")
            if 'openrouter' in key: return 'openrouter'
            if 'openai' in key: return 'openai'
            if 'ollama' in key: return 'ollama'
            if 'gemini' in key or 'google' in key: return 'gemini'
            if 'huggingface' in key or key == 'hf': return 'huggingface'
            return key

        def instantiate_pool(config_list):
            pool = []
            # Sort instances by numeric priority
            for inst_cfg in sorted(config_list, key=lambda x: x.get('priority', 99)):
                if not inst_cfg.get('enabled', True):
                    continue
                    
                prov_name = inst_cfg.get('provider', '')
                norm = normalize_name(prov_name)
                
                # Match driver class by provider name.
                cls = next((c for n, c in loaded_classes.items() if normalize_name(n) == norm), None)
                if not cls and norm in ['local_openai', 'local_qwen']:
                    cls = next((c for n, c in loaded_classes.items() if normalize_name(n) == 'openai'), None)
                    
                if cls:
                    try:
                        instance = cls(inst_cfg)
                        pool.append({
                            'id': inst_cfg.get('id', prov_name),
                            'provider': prov_name,
                            'instance': instance,
                            'max_tokens': inst_cfg.get('max_tokens', 4096),
                            'max_context': inst_cfg.get('max_context', 8000)
                        })
                        self.provider_health[inst_cfg.get('id', prov_name)] = {
                            "status": "online",
                            "last_error": None,
                            "priority": inst_cfg.get('priority', 99)
                        }
                        logger.info(f"Loaded Provider Instance: {inst_cfg.get('id', prov_name)} (Priority: {inst_cfg.get('priority', 99)})")
                    except Exception as e:
                        error_msg = str(e)
                        self.provider_health[inst_cfg.get('id', prov_name or 'unknown')] = {
                            "status": "error",
                            "last_error": error_msg,
                            "priority": inst_cfg.get('priority', 99)
                        }
                        logger.error(f"Failed to load Provider Instance {inst_cfg.get('id')}: {error_msg}")
            return pool

        self.chat_pool = instantiate_pool(self.chat_config)
        self.vision_pool = instantiate_pool(self.vision_config)

    def get_active_config(self) -> Dict[str, Any]:
        """Returns the config of the primary active provider."""
        if not self.chat_pool:
            return {}
        # The pool is already sorted by priority
        primary = self.chat_pool[0]
        # Find the original config for this ID
        return next((c for c in self.chat_config if c.get('id') == primary['id']), {})

    def _execute_with_router(self, pool, method_name, *args, **kwargs):
        """
        Executes a method on the pool of providers in priority order.
        If a provider raises an exception (timeout, rate limit, server error),
        it falls back to the next provider in the pool.
        """
        if not pool:
            return None, "No active providers in the pool"
        total_providers = len(pool)
        self._last_router_meta = {}
        last_error = ""
        last_error_details: Dict[str, Any] = {}
        attempt_log: List[Dict[str, Any]] = []
        strict_mode = kwargs.get("strict_mode")
        paranoid_mode = kwargs.get("paranoid_mode")
        intent_repair_attempts = kwargs.get("intent_repair_attempts")
        allowed_actions = kwargs.get("allowed_actions")
        for idx, item in enumerate(pool, start=1):
            provider_id = item['id']
            instance = item['instance']
            provider_name = str(item.get("provider") or provider_id or "")
            model_hint = self._provider_model_hint(instance)
            
            # Inject limits if the method accepts them (for generate_intent)
            if method_name == 'generate_intent':
                kwargs['max_tokens'] = item.get('max_tokens', 4096)
                kwargs['max_context'] = item.get('max_context', 8000)
            try:
                method = getattr(instance, method_name)
                result = method(*args, **kwargs)
                if method_name == "generate_intent":
                    self._validate_provider_intent_contract(result, provider_name, method_name)
                self._last_router_meta = {
                    "provider_id": str(provider_id),
                    "provider": provider_name,
                    "attempt": idx,
                    "max_attempts": total_providers,
                    "model": model_hint,
                    "provider_used": provider_name,
                    "provider_parse_status": "ok",
                    "provider_attempts": attempt_log + [
                        {
                            "provider_id": str(provider_id),
                            "provider": provider_name,
                            "model": model_hint,
                            "attempt": idx,
                            "status": "success",
                            "reason_code": None,
                            "provider_parse_status": "ok",
                        }
                    ],
                    "provider_attempts_total": total_providers,
                    "provider_fallback_reason": None,
                    "fallback_stage": "provider_success",
                    "error_stage": None,
                    "error_type": None,
                    "error_reason": None,
                    "diagnostic_source": provider_name,
                    "raw_preview": "",
                    "raw_preview_truncated": False,
                    "raw_preview_chars": 0,
                    "semantic_authority": False,
                    "provider_schema_mode": self._provider_schema_mode(method_name, instance, kwargs),
                    "provider_contract_mode": "structured" if "structured" in str(method_name or "") else "intent",
                    "strict_mode": bool(strict_mode) if strict_mode is not None else None,
                    "paranoid_mode": bool(paranoid_mode) if paranoid_mode is not None else None,
                    "intent_repair_attempts": int(intent_repair_attempts) if intent_repair_attempts is not None else None,
                    "allowed_actions_count": len(allowed_actions) if isinstance(allowed_actions, (list, set, tuple)) else None,
                }
                return result, None
            except Exception as e:
                error_msg = str(e)
                reason_code = self._categorize_provider_error(e)
                error_details = self._extract_exception_diagnostics(
                    e,
                    provider_name=provider_name,
                    method_name=method_name,
                    model_hint=model_hint,
                    attempt=idx,
                    max_attempts=total_providers,
                    error_msg=error_msg,
                )
                if error_details:
                    last_error_details = dict(error_details)
                attempt_log.append(
                    {
                        "provider_id": str(provider_id),
                        "provider": provider_name,
                        "model": model_hint,
                        "attempt": idx,
                        "status": "failed",
                        "reason_code": reason_code,
                        "error": error_msg,
                        "provider_parse_status": error_details.get("provider_parse_status") if error_details else reason_code,
                        "provider_fallback_reason": error_details.get("provider_fallback_reason") if error_details else None,
                        "error_stage": error_details.get("error_stage") if error_details else "provider",
                        "error_type": error_details.get("error_type") if error_details else type(e).__name__,
                        "error_reason": error_details.get("error_reason") if error_details else error_msg,
                        "diagnostic_source": error_details.get("diagnostic_source") if error_details else "llm_manager",
                        "raw_preview": error_details.get("raw_preview") if error_details else "",
                        "raw_preview_truncated": error_details.get("raw_preview_truncated") if error_details else False,
                        "raw_preview_chars": error_details.get("raw_preview_chars") if error_details else 0,
                    }
                )
                if provider_id in self.provider_health:
                    self.provider_health[provider_id]["last_error"] = error_msg
                logger.warning(f"Provider {provider_id} failed ({method_name}): {error_msg}. Falling back to next...")
                if method_name in {"generate_structured", "analyze_image_structured"}:
                    self._emit_router_contract_violation(
                        provider=provider_name,
                        provider_id=str(provider_id),
                        instance=instance,
                        method_name=method_name,
                        prompt=self._extract_router_prompt(args, kwargs),
                        raw_response="",
                        error_text=error_msg,
                        contract_name=str(kwargs.get("contract", "") or ""),
                        attempt=idx,
                        max_attempts=total_providers,
                        kwargs=kwargs,
                    )
                last_error = error_msg
                continue
        self._last_router_meta = {
            "provider_used": None,
            "provider_attempts": attempt_log,
            "provider_attempts_total": total_providers,
            "provider_fallback_reason": last_error_details.get("provider_fallback_reason") or self._categorize_router_fallback_reason(last_error),
            "provider_parse_status": last_error_details.get("provider_parse_status") or self._categorize_router_fallback_reason(last_error),
            "fallback_stage": "router_exhausted",
            "semantic_authority": False,
            "provider_schema_mode": self._provider_schema_mode(method_name, None, kwargs),
            "provider_contract_mode": "structured" if "structured" in str(method_name or "") else "intent",
            "strict_mode": bool(strict_mode) if strict_mode is not None else None,
            "paranoid_mode": bool(paranoid_mode) if paranoid_mode is not None else None,
            "intent_repair_attempts": int(intent_repair_attempts) if intent_repair_attempts is not None else None,
            "allowed_actions_count": len(allowed_actions) if isinstance(allowed_actions, (list, set, tuple)) else None,
            "error_stage": last_error_details.get("error_stage") or "llm_manager",
            "error_type": last_error_details.get("error_type") or "provider_error",
            "error_reason": last_error_details.get("error_reason") or last_error,
            "diagnostic_source": last_error_details.get("diagnostic_source") or "llm_manager",
            "raw_preview": last_error_details.get("raw_preview") or "",
            "raw_preview_truncated": bool(last_error_details.get("raw_preview_truncated")),
            "raw_preview_chars": int(last_error_details.get("raw_preview_chars") or 0),
        }
        return None, f"All providers failed. Last error: {last_error}"

    @staticmethod
    def _categorize_provider_error(error: Exception) -> str:
        text = f"{type(error).__name__}: {error}".lower()
        if "timeout" in text or "timed out" in text:
            return "timeout"
        if "rate" in text and "limit" in text:
            return "rate_limit"
        if "schema" in text or "json_schema" in text or "json object" in text or "format" in text:
            return "schema_error"
        if "json" in text or "parse" in text or "invalid json" in text:
            return "provider_parse_error"
        if "auth" in text or "unauthor" in text or "api key" in text:
            return "authentication_error"
        return "provider_error"

    @staticmethod
    def _categorize_router_fallback_reason(last_error: str) -> str:
        text = str(last_error or "").lower()
        if not text:
            return "all_providers_failed"
        if "timeout" in text or "timed out" in text:
            return "timeout"
        if "rate" in text and "limit" in text:
            return "rate_limit"
        if "schema" in text or "json_schema" in text or "json object" in text or "format" in text:
            return "schema_error"
        if "json" in text or "parse" in text or "invalid json" in text:
            return "provider_parse_error"
        if "auth" in text or "unauthor" in text or "api key" in text:
            return "authentication_error"
        return "provider_error"

    @staticmethod
    def _extract_exception_diagnostics(
        error: Exception,
        *,
        provider_name: str,
        method_name: str,
        model_hint: str,
        attempt: int,
        max_attempts: int,
        error_msg: str,
    ) -> Dict[str, Any]:
        details = getattr(error, "details", None)
        if isinstance(details, dict) and details:
            out = dict(details)
        else:
            out = {}
        if not out:
            return {}
        out.setdefault("provider_used", provider_name)
        out.setdefault("provider_attempts", [])
        out.setdefault("provider_attempts_total", max_attempts)
        out.setdefault("provider_schema_mode", LLMManager._provider_schema_mode(method_name, None, {}))
        out.setdefault("provider_contract_mode", "structured" if "structured" in str(method_name or "") else "intent")
        out.setdefault("diagnostic_source", provider_name or "provider")
        out.setdefault("error_stage", out.get("error_stage") or "provider")
        out.setdefault("error_type", out.get("error_type") or type(error).__name__)
        out.setdefault("error_reason", out.get("error_reason") or error_msg)
        out.setdefault("provider_parse_status", out.get("provider_parse_status") or "unknown_error")
        out.setdefault("provider_fallback_reason", out.get("provider_fallback_reason") or "provider_exception")
        out.setdefault("semantic_authority", bool(out.get("semantic_authority", False)))
        preview = LLMManager._normalize_preview_fields(out.get("raw_preview"), out.get("raw_preview_truncated"), out.get("raw_preview_chars"))
        out.update(preview)
        return out

    @staticmethod
    def _normalize_preview_fields(raw_preview: Any, truncated: Any, chars: Any) -> Dict[str, Any]:
        preview = str(raw_preview or "")
        try:
            chars_i = int(chars or len(preview))
        except Exception:
            chars_i = len(preview)
        return {
            "raw_preview": preview,
            "raw_preview_truncated": bool(truncated),
            "raw_preview_chars": max(0, chars_i),
        }

    @staticmethod
    def _provider_schema_mode(method_name: str, instance: Any = None, kwargs: Optional[Dict[str, Any]] = None) -> str:
        method = str(method_name or "").strip().lower()
        if method == "generate_structured":
            return "structured_json"
        if method == "analyze_image_structured":
            return "structured_json_vision"
        if method == "generate_intent":
            return "intent_json"
        if method == "generate_text":
            return "text"
        return "unknown"

    @staticmethod
    def _provider_model_hint(instance: Any) -> str:
        for attr in ("model_name", "model", "model_id", "model_name_or_path"):
            try:
                value = getattr(instance, attr, "")
            except Exception:
                value = ""
            if value:
                return str(value)
        return "unknown"

    @staticmethod
    def _intent_has_provider_diagnostics(intent: AgentIntent) -> bool:
        state_summary = getattr(intent, "state_summary", None)
        if not isinstance(state_summary, dict):
            return False
        diagnostic_keys = (
            "provider_parse_status",
            "provider_fallback_reason",
            "provider_used",
            "provider_attempts",
            "provider_attempts_total",
            "provider_schema_mode",
            "provider_contract_mode",
            "error_code",
            "semantic_authority",
        )
        for key in diagnostic_keys:
            value = state_summary.get(key)
            if value not in (None, "", [], {}):
                return True
        return False

    @classmethod
    def _validate_provider_intent_contract(cls, intent: AgentIntent, provider_name: str, method_name: str) -> None:
        if not isinstance(intent, AgentIntent):
            raise ProviderContractError(f"{provider_name} returned a non-AgentIntent payload for {method_name}.")

        action = str(getattr(intent, "action", "") or "").strip()
        response_text = str(getattr(intent, "response_text", "") or "").strip()

        if not action:
            raise ProviderContractError(
                f"{provider_name} returned an intent without action for {method_name}.",
                details=ILLMProvider.build_contract_diagnostics(
                    provider_used=provider_name,
                    error_stage="llm_manager",
                    error_type="provider_contract_error",
                    error_reason="missing_action",
                    raw_response=getattr(intent, "state_summary", None),
                    provider_parse_status="missing_action",
                    provider_fallback_reason="provider_contract_error",
                    provider_schema_mode=cls._provider_schema_mode(method_name, None, {}),
                    provider_contract_mode="intent",
                    semantic_authority=False,
                    diagnostic_source="llm_manager",
                ),
            )

        if action == "reply" and not response_text:
            raise ProviderContractError(
                f"{provider_name} returned reply without response_text for {method_name}.",
                details=ILLMProvider.build_contract_diagnostics(
                    provider_used=provider_name,
                    error_stage="llm_manager",
                    error_type="provider_contract_error",
                    error_reason="missing_response_text",
                    raw_response=getattr(intent, "state_summary", None),
                    provider_parse_status="missing_response_text",
                    provider_fallback_reason="provider_contract_error",
                    provider_schema_mode=cls._provider_schema_mode(method_name, None, {}),
                    provider_contract_mode="intent",
                    semantic_authority=False,
                    diagnostic_source="llm_manager",
                ),
            )

        if action in {"unknown", "error"} and not cls._intent_has_provider_diagnostics(intent):
            raise ProviderContractError(
                f"{provider_name} returned {action} without provider diagnostics for {method_name}.",
                details=ILLMProvider.build_contract_diagnostics(
                    provider_used=provider_name,
                    error_stage="llm_manager",
                    error_type="provider_contract_error",
                    error_reason="missing_provider_diagnostics",
                    raw_response=getattr(intent, "state_summary", None),
                    provider_parse_status="unknown_error",
                    provider_fallback_reason="provider_contract_error",
                    provider_schema_mode=cls._provider_schema_mode(method_name, None, {}),
                    provider_contract_mode="intent",
                    semantic_authority=False,
                    diagnostic_source="llm_manager",
                ),
            )

    @staticmethod
    def _extract_router_prompt(args: Any, kwargs: Dict[str, Any]) -> str:
        prompt = kwargs.get("prompt")
        if prompt is not None:
            return str(prompt)
        if isinstance(args, tuple) and args:
            first = args[0]
            if isinstance(first, str):
                return first
        return ""

    def _emit_router_contract_violation(
        self,
        *,
        provider: str,
        provider_id: str,
        instance: Any,
        model_hint: str = "",
        method_name: str,
        prompt: str,
        raw_response: Any,
        error_text: str,
        contract_name: str,
        attempt: int,
        max_attempts: int,
        kwargs: Dict[str, Any],
    ) -> None:
        try:
            write_contract_violation(
                provider=str(provider or "provider"),
                model=str(model_hint or self._provider_model_hint(instance)),
                contract_name=str(contract_name or method_name),
                prompt=str(prompt or ""),
                raw_response=raw_response,
                error_text=str(error_text or "contract_violation"),
                attempt=int(attempt),
                max_attempts=int(max_attempts),
                session_id=str(kwargs.get("session_id") or ""),
                work_id=str(kwargs.get("work_id") or ""),
                trace_id=str(kwargs.get("trace_id") or ""),
                step_id=str(kwargs.get("step_id") or ""),
                extra={
                    "stage": "llm_router",
                    "method": str(method_name or ""),
                    "provider_id": str(provider_id or ""),
                },
            )
        except Exception as artifact_err:
            logger.warning("LLM router contract artifact failed: %s", artifact_err)

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] = None, **kwargs) -> AgentIntent:
        result, err = self._execute_with_router(
            self.chat_pool, 'generate_intent', 
            user_input, history, system_prompt, attachments=attachments, **kwargs
        )
        if result:
            if not result.model_used:
                result.model_used = self._last_router_meta.get("model")
            if isinstance(result.state_summary, dict):
                result.state_summary.setdefault("provider_used", self._last_router_meta.get("provider_used"))
                result.state_summary.setdefault("provider_attempts", self._last_router_meta.get("provider_attempts"))
                result.state_summary.setdefault("provider_attempts_total", self._last_router_meta.get("provider_attempts_total"))
                result.state_summary.setdefault("provider_fallback_reason", self._last_router_meta.get("provider_fallback_reason"))
                result.state_summary.setdefault("provider_parse_status", self._last_router_meta.get("provider_parse_status"))
                result.state_summary.setdefault("provider_schema_mode", self._last_router_meta.get("provider_schema_mode"))
                result.state_summary.setdefault("provider_contract_mode", self._last_router_meta.get("provider_contract_mode"))
                result.state_summary.setdefault("error_stage", self._last_router_meta.get("error_stage"))
                result.state_summary.setdefault("error_type", self._last_router_meta.get("error_type"))
                result.state_summary.setdefault("error_reason", self._last_router_meta.get("error_reason"))
                result.state_summary.setdefault("diagnostic_source", self._last_router_meta.get("diagnostic_source"))
                result.state_summary.setdefault("raw_preview", self._last_router_meta.get("raw_preview"))
                result.state_summary.setdefault("raw_preview_truncated", self._last_router_meta.get("raw_preview_truncated"))
                result.state_summary.setdefault("raw_preview_chars", self._last_router_meta.get("raw_preview_chars"))
                result.state_summary.setdefault("semantic_authority", False)
            return result
            
        fallback = AgentIntent(
            thought=f"Router Error: {err}",
            action="error",
            params={"error": "router_failure", "details": err},
            response_text="I couldn't contact my brain providers after trying all fallbacks."
        )
        fallback.state_summary = {
            "provider_used": self._last_router_meta.get("provider_used"),
            "provider_attempts": self._last_router_meta.get("provider_attempts"),
            "provider_attempts_total": self._last_router_meta.get("provider_attempts_total"),
            "provider_fallback_reason": self._last_router_meta.get("provider_fallback_reason") or "all_providers_failed",
            "provider_parse_status": self._last_router_meta.get("provider_parse_status") or "unknown_error",
            "provider_schema_mode": self._last_router_meta.get("provider_schema_mode"),
            "provider_contract_mode": self._last_router_meta.get("provider_contract_mode"),
            "strict_mode": self._last_router_meta.get("strict_mode"),
            "paranoid_mode": self._last_router_meta.get("paranoid_mode"),
            "intent_repair_attempts": self._last_router_meta.get("intent_repair_attempts"),
            "allowed_actions_count": self._last_router_meta.get("allowed_actions_count"),
            "error_stage": self._last_router_meta.get("error_stage") or "llm_manager",
            "error_type": self._last_router_meta.get("error_type") or "provider_error",
            "error_reason": self._last_router_meta.get("error_reason") or err,
            "diagnostic_source": self._last_router_meta.get("diagnostic_source") or "llm_manager",
            "raw_preview": self._last_router_meta.get("raw_preview") or "",
            "raw_preview_truncated": self._last_router_meta.get("raw_preview_truncated") or False,
            "raw_preview_chars": self._last_router_meta.get("raw_preview_chars") or 0,
            "semantic_authority": False,
        }
        return fallback

    def get_last_router_meta(self) -> Dict[str, Any]:
        return dict(self._last_router_meta or {})

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """
        Specialized method to analyze an image using the configured vision pool.
        Finds the first vision provider that succeeds.
        """
        # For vision, use vision_pool if available, otherwise fallback to chat_pool
        pool = self.vision_pool if self.vision_pool else self.chat_pool
        result, err = self._execute_with_router(pool, 'analyze_image', image_path, prompt)
        if result:
            return result
        return f"Error analyzing image: {err}"

    def analyze_image_structured(self, image_path: str, prompt: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Structured image analysis routed to vision providers.
        Provider/driver is responsible for parsing and normalization.
        """
        pool = self.vision_pool if self.vision_pool else self.chat_pool
        result, err = self._execute_with_router(
            pool,
            'analyze_image_structured',
            image_path=image_path,
            prompt=prompt,
            **kwargs,
        )
        if err:
            logger.error(f"Structured vision router failed: {err}")
        if isinstance(result, dict):
            return result
        if result is not None:
            meta = self._last_router_meta if isinstance(self._last_router_meta, dict) else {}
            self._emit_router_contract_violation(
                provider=str(meta.get("provider") or "provider"),
                provider_id=str(meta.get("provider_id") or ""),
                instance=object(),
                model_hint=str(meta.get("model") or "unknown"),
                method_name="analyze_image_structured",
                prompt=str(prompt or ""),
                raw_response=result,
                error_text="Router returned non-dict structured vision payload",
                contract_name=str(kwargs.get("contract", "") or "analyze_image_structured"),
                attempt=int(meta.get("attempt") or 1),
                max_attempts=int(meta.get("max_attempts") or 1),
                kwargs=kwargs,
            )
        return None

    def generate_text(self, prompt: str, system_prompt: str = None, **kwargs) -> Optional[str]:
        """
        Generic text generation routing to the primary chat provider.
        Used for summarization, recovery, and other conversational needs.
        """
        result, err = self._execute_with_router(
            self.chat_pool, 'generate_text', 
            prompt=prompt, system_prompt=system_prompt, **kwargs
        )
        return result

    def generate_structured_text(self, prompt: str, system_prompt: str = None, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Structured generation routed to providers.
        Parsing/normalization must happen at driver level, not in core/planner.
        """
        result, err = self._execute_with_router(
            self.chat_pool,
            'generate_structured',
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs,
        )
        if err:
            logger.error(f"Structured generation router failed: {err}")
        if isinstance(result, dict):
            return result
        if result is not None:
            meta = self._last_router_meta if isinstance(self._last_router_meta, dict) else {}
            self._emit_router_contract_violation(
                provider=str(meta.get("provider") or "provider"),
                provider_id=str(meta.get("provider_id") or ""),
                instance=object(),
                model_hint=str(meta.get("model") or "unknown"),
                method_name="generate_structured",
                prompt=str(prompt or ""),
                raw_response=result,
                error_text="Router returned non-dict structured payload",
                contract_name=str(kwargs.get("contract", "") or "generate_structured"),
                attempt=int(meta.get("attempt") or 1),
                max_attempts=int(meta.get("max_attempts") or 1),
                kwargs=kwargs,
            )
        return None

    def summarize_output(self, text: str) -> str:
        """
        Generates a concise semantic summary of a large text (e.g., a tool log).
        """
        # Heuristic: if it's already small, don't waste tokens
        if len(text) < 500:
            return text
            
        sys_prompt = "You are a technical log analysis specialist. Summarize the log very concisely in English."
        result, err = self._execute_with_router(
            self.chat_pool, 'generate_text', 
            prompt=f"Capture the essence of this technical log. If it is an error, describe the root cause.\\n\\nLOG:\\n{text[:4000]}", 
            system_prompt=sys_prompt
        )
        
        if result:
            return result
            
        logger.error(f"Summarizer router failed: {err}")
        return text[:500] + "... (Summary Failed)"
