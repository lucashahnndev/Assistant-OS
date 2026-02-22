import json
import os
import threading
from utils.logging_config import get_logger

logger = get_logger("ConfigManager")

class ConfigManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    @staticmethod
    def get_data_dir():
        """Returns the base data directory for AOSD, prioritizing local data for dev."""
        # 1. Environment Variable Override
        env_dir = os.environ.get("AOSD_DATA_DIR")
        if env_dir:
            return env_dir
            
        # 2. Local data directory (Development preference)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        local_data = os.path.join(project_root, 'data')
        if os.path.exists(local_data):
            return local_data
            
        # 3. Standard User Fallback
        return os.path.expanduser("~/aosd")

    def __init__(self, config_file=None):
        if hasattr(self, 'initialized') and self.initialized:
            return
        
        self.base_data_dir = self.get_data_dir()
        if not os.path.exists(self.base_data_dir):
            os.makedirs(self.base_data_dir, exist_ok=True)
            logger.info(f"Created AOSD data directory at: {self.base_data_dir}")

        if config_file is None:
            config_file = os.path.join(self.base_data_dir, 'config.json')
            
        self.config_file = config_file
        self.config_data = {}
        self.load()
        self.initialized = True

    def load(self):
        """Loads configuration from file and environment variables."""
        # Load .env file from the dynamic data directory
        from dotenv import load_dotenv
        env_path = os.path.join(self.base_data_dir, '.env')
        load_dotenv(env_path)
        
        # Also try to load from project root as fallback for development
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        load_dotenv(os.path.join(project_root, '.env'))

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.config_data = self._substitute_env_vars(data)
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                self.config_data = {}
        else:
            logger.warning(f"Config file not found: {self.config_file}")
            self.config_data = {}

    def _substitute_env_vars(self, data):
        """Recursively substitutes string values starting with ENV_ from os.environ."""
        if isinstance(data, dict):
            return {k: self._substitute_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._substitute_env_vars(v) for v in data]
        elif isinstance(data, str) and data.startswith("ENV_"):
            # Extract variable name from value (e.g., "ENV_TELEGRAM_TOKEN" -> "TELEGRAM_TOKEN" or match full name)
            # Strategy: User said "coloca ENV_OPENAI_KEY". 
            # I will check if the *exact string* exists as an env var first.
            # Strategy: User said "coloca ENV_OPENAI_KEY" in config.
            # 1. Try exact match (e.g. is there a var named ENV_OPENAI_KEY?)
            env_val = os.getenv(data)
            if env_val:
                return env_val
            
            # 2. Try stripping ENV_ prefix (e.g. ENV_OPENAI_KEY -> OPENAI_KEY)
            # This allows config to say "ENV_TOKEN" and .env to have "TOKEN"
            stripped_key = data.replace("ENV_", "", 1)
            env_val_stripped = os.getenv(stripped_key)
            if env_val_stripped:
                return env_val_stripped

            return data # Return original if not found
        else:
            return data

    def get_config(self, key, default=None):
        """Retrieves a configuration value."""
        return self.config_data.get(key, default)

    def get(self, key, default=None):
        """Retrieves a configuration value (alias)."""
        return self.get_config(key, default)

    def get_tts_config(self):
        """Returns TTS specific configuration."""
        # Try new cortex path first
        cortex_tts = self.get("cortex", {}).get("audio", {}).get("tts")
        if cortex_tts:
            return cortex_tts

        # Fallback to legacy path
        default_tts = {
            "provider": "system",
            "providers": {
                "system": {"rate": 150, "volume": 1.0},
                "google_cloud": {},
                "edge_tts": {"voice": "pt-BR-FranciscaNeural"}
            }
        }
        return self.get("tts", default_tts)

    def get_llm_config(self):
        """Returns LLM specific configuration."""
        # Try new cortex path first
        cortex_chat = self.get("cortex", {}).get("chat")
        if cortex_chat:
            return cortex_chat

        # Fallback to legacy path
        default_llm = {
            "provider": "openrouter",
            "providers": {
                "openrouter": {
                    "api_key": "",
                    "model": "openai/gpt-3.5-turbo"
                },
                "openai": {
                    "api_key": ""
                },
                "ollama": {
                    "model": "llama3",
                    "url": "http://localhost:11434/api/chat"
                }
            }
        }
        return self.get("llm", default_llm)

    def get_telegram_config(self):
        return {
            "token": self.get("telegram_token"),
            "allowed_users": self.get("allowed_users")
        }

    def get_interfaces_config(self):
        """Returns active interfaces configuration."""
        default_interfaces = {
            "voice": {
                "enabled": True,
                "wake_word": "atlas"
            },
            "telegram": {
                "enabled": True, 
                "token": "",
                "allowed_users": []
            },
            "browser": {
                "enabled": False
            }
        }
        return self.get("interfaces", default_interfaces)

    def get_stt_config(self):
        """Returns STT (Speech-to-Text) configuration."""
        # Try new cortex path first
        cortex_stt = self.get("cortex", {}).get("audio", {}).get("stt")
        if cortex_stt:
            return cortex_stt

        # Fallback to legacy path
        default_stt = {
            "provider": "google",
            "providers": {
                "google": { "language": "pt-BR" },
                "vosk": { "model_path": "model/vosk-model-small-pt-0.3" },
                "openai": { "api_key": "" } 
            }
        }
        return self.get("stt", default_stt)

    def get_vision_config(self):
        """Returns Vision specific configuration."""
        default_vision = {
            "provider": "google",
            "providers": {
                "google": {
                    "model": "gemini-2.0-flash"
                }
            }
        }
        return self.get("cortex", {}).get("vision", default_vision)

    def get_skills_config(self):
        """Returns the skills enablement configuration."""
        return self.get("skills", {})

    def get_skill_config(self, skill_name):
        """Returns configuration for a specific skill."""
        return self.get_skills_config().get(skill_name, {})

    def get_location_config(self):
        """Returns location specific configuration."""
        default_loc = {
            "mode": "auto",
            "default": {
                "city": "Unknown",
                "latitude": 0.0,
                "longitude": 0.0
            }
        }
        return self.get("location", default_loc)
