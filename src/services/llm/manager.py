from typing import List, Dict, Optional, Any
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider
from utils.plugin_loader import PluginLoader
from config import ConfigManager
from utils.contract_artifacts import write_contract_violation
from core.error_classifier import ErrorClassifier
from core.errors import AgentSemanticError, SyntaxError as AgentSyntaxError, TransportError, ProviderQuotaError, ProviderAuthError, ProviderRateLimitError
from core.health import health_monitor
from utils.event_bus import global_event_bus
from services.agent_runtime_v2.flags import get_max_provider_attempts_per_turn
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
                
                # Match driver class. If local compatible OpenAI server, map to standard OpenAI driver.
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
                        logger.info(f"Loaded Provider Instance: {inst_cfg.get('id', prov_name)} (Priority: {inst_cfg.get('priority', 99)})")
                    except Exception as e:
                        logger.error(f"Failed to load Provider Instance {inst_cfg.get('id')}: {e}")
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
        Routing is bounded and classified; no provider is retried in-place.
        """
        if not pool:
            return None, "No active providers in the pool"
        total_providers = min(len(pool), get_max_provider_attempts_per_turn(self.config_manager))
        classifier = ErrorClassifier()
        self._last_router_meta = {}
        last_error = ""
        for idx, item in enumerate(pool[:total_providers], start=1):
            provider_id = item['id']
            provider_name = str(item.get("provider") or provider_id or "")
            
            if not health_monitor.is_available(provider_id):
                logger.info(f"Skipping degraded/offline provider {provider_id}")
                continue

            instance = item['instance']
            
            # Inject limits if the method accepts them (for generate_intent)
            if method_name == 'generate_intent':
                kwargs['max_tokens'] = item.get('max_tokens', 4096)
                kwargs['max_context'] = item.get('max_context', 8000)
            try:
                method = getattr(instance, method_name)
                result = method(*args, **kwargs)
                
                # Mark success
                health_monitor.record_success(provider_id)
                
                # Inject model hint and fallback status
                if hasattr(result, "task_label") or hasattr(result, "action"):  # It's an AgentIntent
                    # We can't easily add fields if the model doesn't support it, but we can set properties
                    setattr(result, "model_used", self._provider_model_hint(instance))
                    setattr(result, "fallback_occurred", idx > 1)

                self._last_router_meta = {
                    "provider_id": str(provider_id),
                    "provider": provider_name,
                    "attempt": idx,
                    "max_attempts": total_providers,
                    "model": self._provider_model_hint(instance),
                }
                return result, None
            except ProviderQuotaError as e:
                health_monitor.record_failure(provider_id, str(e), is_fatal=True)
                global_event_bus.emit_threadsafe({
                    "type": "provider_alert", 
                    "provider": provider_id, 
                    "reason": "quota_exceeded",
                    "message": "The provider has run out of credits/quota."
                })
                logger.error(f"Provider {provider_id} quota exceeded. Emitted alert.")
                last_error = str(e)
                continue
            except ProviderAuthError as e:
                health_monitor.record_failure(provider_id, str(e), is_fatal=True)
                global_event_bus.emit_threadsafe({
                    "type": "provider_alert", 
                    "provider": provider_id, 
                    "reason": "auth_failed",
                    "message": "The provider's authentication key is invalid."
                })
                logger.error(f"Provider {provider_id} auth failed. Emitted alert.")
                last_error = str(e)
                continue
            except ProviderRateLimitError as e:
                health_monitor.record_failure(provider_id, str(e), is_fatal=False)
                logger.warning(f"Provider {provider_id} rate limited.")
                last_error = str(e)
                continue
            except AgentSemanticError as e:
                self._last_router_meta = {
                    "provider_id": str(provider_id),
                    "provider": provider_name,
                    "attempt": idx,
                    "max_attempts": total_providers,
                    "model": self._provider_model_hint(instance),
                    "error_type": "AgentSemanticError",
                    "error_code": getattr(getattr(e, "code", None), "value", str(getattr(e, "code", ""))),
                }
                raise
            except Exception as e:
                classified = classifier.classify(e)
                error_msg = classified.message
                logger.warning(
                    "Provider %s failed (%s): %s | classified=%s",
                    provider_id,
                    method_name,
                    error_msg,
                    classified.error_type,
                )
                self._last_router_meta = {
                    "provider_id": str(provider_id),
                    "provider": provider_name,
                    "attempt": idx,
                    "max_attempts": total_providers,
                    "model": self._provider_model_hint(instance),
                    "error_type": classified.error_type,
                    "error_code": classified.error_code.value,
                }
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
        self._last_router_meta = {}
        return None, f"All providers failed. Last error: {last_error}"

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
            return result
            
        return AgentIntent(
            thought=f"Router Error: {err}",
            action="error",
            params={"error": "router_failure", "details": err},
            response_text="I couldn't contact my brain providers after trying all fallbacks."
        )

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
