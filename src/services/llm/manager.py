from typing import List, Dict, Optional, Any
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider
from utils.plugin_loader import PluginLoader
from config import ConfigManager
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
        
        # Failsafe if not migrated properly yet
        if isinstance(self.chat_config, dict):
             self.chat_config = [] 
        if isinstance(self.vision_config, dict):
             self.vision_config = []

    def _load_providers(self):
        self.chat_pool = []
        self.vision_pool = []
        
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        drivers_path = os.path.join(root_dir, 'drivers', 'llm')
        
        loaded_classes = PluginLoader.load_plugins(drivers_path, ILLMProvider)
        
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
                
                if 'api_key_ref' in inst_cfg and not inst_cfg.get('api_key'):
                    inst_cfg['api_key'] = inst_cfg['api_key_ref']
                
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
        If a provider raises an exception (timeout, rate limit, server error),
        it falls back to the next provider in the pool.
        """
        if not pool:
            return None, "No active providers in the pool"
            
        last_error = ""
        for item in pool:
            provider_id = item['id']
            instance = item['instance']
            
            # Inject limits if the method accepts them (for generate_intent)
            if method_name == 'generate_intent':
                kwargs['max_tokens'] = item.get('max_tokens', 4096)
                kwargs['max_context'] = item.get('max_context', 8000)
            try:
                method = getattr(instance, method_name)
                result = method(*args, **kwargs)
                return result, None
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Provider {provider_id} failed ({method_name}): {error_msg}. Falling back to next...")
                last_error = error_msg
                continue
                
        return None, f"All providers failed. Last error: {last_error}"

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] = None) -> AgentIntent:
        result, err = self._execute_with_router(
            self.chat_pool, 'generate_intent', 
            user_input, history, system_prompt, attachments=attachments
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
