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
        self._load_config()
        self._load_providers()
        
    def reload(self):
        logger.info("Hot Reloading TTSManager...")
        self._load_config()
        self._load_providers()
        logger.info("TTSManager Reloaded with new pool.")

    def _load_config(self):
        self.tts_config = self.config_manager.get_tts_config()

    def _load_providers(self):
        self.tts_pool = []
        providers_dir = os.path.join(os.path.dirname(__file__), 'providers')
        
        loaded_classes = PluginLoader.load_plugins(providers_dir, ITTSProvider)
        
        if not loaded_classes:
            logger.warning("No TTS Providers found!")
            return

        def normalize_name(name):
            key = name.lower().replace("_provider", "")
            if 'edge' in key: return 'edge_tts'
            if 'google' in key: return 'google_cloud'
            return key

        for inst_cfg in sorted(self.tts_config, key=lambda x: x.get('priority', 99)):
            if not inst_cfg.get('enabled', True):
                continue
                
            prov_name = inst_cfg.get('provider', '')
            norm = normalize_name(prov_name)
            
            def match_class(cname):
                return normalize_name(cname) == norm or cname == norm
                
            cls = next((c for n, c in loaded_classes.items() if match_class(n)), None)
            
            if cls:
                try:
                    instance = cls(inst_cfg)
                    self.tts_pool.append({
                        'id': inst_cfg.get('id', prov_name),
                        'provider': prov_name,
                        'instance': instance
                    })
                    logger.info(f"Loaded TTS Provider Instance: {inst_cfg.get('id', prov_name)} (Priority: {inst_cfg.get('priority', 99)})")
                except Exception as e:
                    logger.error(f"Failed to instantiate TTS Provider {prov_name}: {e}")

    def generate(self, text) -> bytes:
        if not text:
            return b""

        if not self.tts_pool:
            logger.error("No active TTS providers in the pool.")
            return b""
            
        for item in self.tts_pool:
            provider_id = item['id']
            instance = item['instance']
            try:
                if instance.is_available():
                    content = instance.generate(text)
                    if content:
                        return content
                    else:
                        logger.warning(f"TTS Provider {provider_id} returned empty bytes. Falling back...")
                else:
                    logger.warning(f"TTS Provider {provider_id} is unavailable. Falling back...")
            except Exception as e:
                logger.warning(f"TTS Provider {provider_id} failed: {e}. Falling back to next...")
                continue
                
        logger.error("All TTS providers failed to generate audio.")
        return b""
