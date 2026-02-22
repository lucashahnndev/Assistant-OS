from config import ConfigManager
from utils.plugin_loader import PluginLoader
from .providers.base import ITTSProvider
import os

from utils.logging_config import get_logger

# Configure logging
logger = get_logger(__name__)

class TTSManager:
    def __init__(self):
        self.config_manager = ConfigManager()
        self.tts_config = self.config_manager.get_tts_config()
        
        self.providers = {}
        self.primary_provider = None
        self.fallback_provider = None
        
        self._load_providers()

    def _load_providers(self):
        # Path to providers directory
        providers_dir = os.path.join(os.path.dirname(__file__), 'providers')
        
        # Load all plugins implementing ITTSProvider
        loaded_classes = PluginLoader.load_plugins(providers_dir, ITTSProvider)
        
        for name, provider_class in loaded_classes.items():
            # Standardize names: 'edge' from 'edge.py' becomes 'edge_tts' if needed
            # For now, we use the module name as the key (e.g., 'edge', 'google', 'system')
            # But our config uses 'edge_tts', 'google_cloud'. 
            # We need a mapping or we rename the files/keys. 
            # Let's handle a simple mapping based on common names or config keys.
            
            # Helper to map filename to config key
            key_map = {
                'edge': 'edge_tts',
                'google': 'google_cloud',
                'system': 'system'
            }
            
            config_key = key_map.get(name, name)
            
            try:
                # Instantiate with specific config
                provider_config = self.tts_config['providers'].get(config_key, {})
                instance = provider_class(provider_config)
                self.providers[config_key] = instance
                logger.info(f"Loaded TTS Provider: {config_key} ({name})")
            except Exception as e:
                logger.error(f"Failed to instantiate TTS Provider {name}: {e}")

        # Set Primary and Fallback
        primary_name = self.tts_config.get('provider', 'system')
        self.primary_provider = self.providers.get(primary_name)
        
        fallback_name = self.tts_config.get('fallback', 'system')
        self.fallback_provider = self.providers.get(fallback_name)

        if not self.primary_provider:
             logger.warning(f"Primary TTS provider '{primary_name}' not found. Using Fallback.")
             self.primary_provider = self.fallback_provider

    def speak(self, text):
        if not text:
            return

        success = False
        
        # Try Primary
        if self.primary_provider and self.primary_provider.is_available():
            try:
                success = self.primary_provider.speak(text)
            except Exception as e:
                logger.error(f"Primary TTS provider failed: {e}")
                success = False
        
        # Try Fallback if Primary failed
        if not success and self.fallback_provider:
            logger.info("Switching to Fallback TTS Provider.")
            try:
                self.fallback_provider.speak(text)
            except Exception as e:
                 logger.error(f"Fallback TTS provider failed: {e}")

