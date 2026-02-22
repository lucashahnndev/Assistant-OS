from typing import List, Dict, Optional
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
        self.chat_config = self.config_manager.get_llm_config()
        self.vision_config = self.config_manager.get_vision_config()
        
        self.chat_providers = {}
        self.vision_providers = {}
        
        self._load_providers()
        
        # Set active chat provider
        primary_chat = self.chat_config.get('provider', 'openrouter')
        self.active_chat_provider = self.chat_providers.get(primary_chat)

    def reload(self):
        """Reloads configuration and re-instantiates all providers."""
        logger.info("Hot Reloading LLMManager...")
        self.chat_config = self.config_manager.get_llm_config()
        self.vision_config = self.config_manager.get_vision_config()
        
        # Clear existing instances to force re-instantiation with new config/keys
        self.chat_providers = {}
        self.vision_providers = {}
        
        self._load_providers()
        
        primary_chat = self.chat_config.get('provider', 'openrouter')
        self.active_chat_provider = self.chat_providers.get(primary_chat)
        logger.info(f"LLMManager Reloaded. Active Chat Provider: {primary_chat}")

    def _load_providers(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        drivers_path = os.path.join(root_dir, 'drivers', 'llm')
        
        loaded_classes = PluginLoader.load_plugins(drivers_path, ILLMProvider)
        
        if not loaded_classes:
            logger.warning("No LLM Providers found!")
            return

        # Helper to normalize names
        def normalize_name(name):
            key = name.lower().replace("_driver", "").replace("provider", "")
            if 'openrouter' in key: return 'openrouter'
            if 'openai' in key: return 'openai'
            if 'ollama' in key: return 'ollama'
            if 'gemini' in key or 'google' in key: return 'gemini'
            return key

        # Instantiate Chat Providers
        for name, cfg in self.chat_config.get('providers', {}).items():
            norm = normalize_name(name)
            cls = next((c for n, c in loaded_classes.items() if normalize_name(n) == norm), None)
            if cls:
                try:
                    self.chat_providers[name] = cls(cfg)
                    logger.info(f"Loaded Chat Provider: {name}")
                except Exception as e:
                    logger.error(f"Failed to load Chat Provider {name}: {e}")

        # Instantiate Vision Providers
        for name, cfg in self.vision_config.get('providers', {}).items():
            norm = normalize_name(name)
            cls = next((c for n, c in loaded_classes.items() if normalize_name(n) == norm), None)
            if cls:
                try:
                    self.vision_providers[name] = cls(cfg)
                    logger.info(f"Loaded Vision Provider: {name}")
                except Exception as e:
                    logger.error(f"Failed to load Vision Provider {name}: {e}")

    def set_active_provider(self, provider_name: str):
        if provider_name in self.chat_providers:
            self.active_chat_provider = self.chat_providers[provider_name]
            logger.info(f"Active Chat Provider set to: {provider_name}")
        else:
            logger.warning(f"Chat Provider '{provider_name}' not found.")
            if self.chat_providers:
                first = list(self.chat_providers.keys())[0]
                self.active_chat_provider = self.chat_providers[first]
                logger.warning(f"Falling back to chat provider: {first}")

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] = None) -> AgentIntent:
        if not self.active_chat_provider:
            return AgentIntent(
                thought="No active LLM provider set",
                action="error",
                params={"error": "no_provider"},
                response_text="I have no brain connected."
            )
        
        return self.active_chat_provider.generate_intent(user_input, history, system_prompt, attachments=attachments)

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """
        Specialized method to analyze an image using the configured vision provider.
        """
        # Try to use the vision-specific provider from config if available
        provider_name = self.vision_config.get('provider')
        
        provider = self.vision_providers.get(provider_name) if provider_name else self.active_chat_provider
        
        if not provider:
            return "Erro: Nenhum provedor de visão configurado ou disponível."
            
        return provider.analyze_image(image_path, prompt)

    def summarize_output(self, text: str) -> str:
        """
        Generates a concise semantic summary of a large text (e.g., a tool log).
        """
        if not self.active_chat_provider:
            return "Erro: Nenhum provedor LLM ativo para sumarização."
        
        # Heuristic: if it's already small, don't waste tokens
        if len(text) < 500:
            return text
            
        prompt = (
            "Capture a essência desse log técnico. Se for um erro, descreva a causa raiz. "
            "Se for uma listagem, resuma o que foi listado. Mantenha menos de 200 caracteres.\n\n"
            f"LOG:\n{text[:4000]}" # Limit input to avoid token overflow in summarizer itself
        )
        
        system_prompt = "Você é um especialista em análise de logs técnicos. Resuma o log de forma muito concisa em português."
        
        return self.active_chat_provider.generate_text(prompt, system_prompt=system_prompt)
