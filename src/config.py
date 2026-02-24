import json
import os
import threading

class ConfigManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, config_file=None):
        if hasattr(self, 'initialized') and self.initialized:
            return
        
        if config_file is None:
            # Default location
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_file = os.path.join(base_dir, 'data', 'config.json')
            
        self.config_file = config_file
        self.config_data = {}
        self.load()
        self.initialized = True

    def load(self):
        """Loads configuration from file."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}")
                self.config_data = {}
        else:
            print(f"Config file not found: {self.config_file}")
            self.config_data = {}

    def get(self, key, default=None):
        """Retrieves a configuration value with environment variable resolution."""
        value = self.config_data.get(key, default)
        return self._resolve_env_vars(value)

    def _resolve_env_vars(self, value):
        """Recursively resolves strings starting with ENV_ to environment variables."""
        if isinstance(value, str) and value.startswith("ENV_"):
            env_key = value[4:]
            return os.environ.get(env_key, value)
        elif isinstance(value, dict):
            return {k: self._resolve_env_vars(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._resolve_env_vars(i) for i in value]
        return value

    def get_tts_config(self):
        """Returns TTS specific configuration."""
        # Default structure if not present
        default_tts = {
            "provider": "system", # Default to system (offline) if not set
            "providers": {
                "system": {"rate": 150, "volume": 1.0},
                "google_cloud": {}, # Credentials usually loaded from env or separate file
                "edge_tts": {"voice": "pt-BR-FranciscaNeural"}
            }
        }
        return self.get("tts", default_tts)

    def get_telegram_config(self):
        return {
            "token": self.get("telegram_token"),
            "allowed_users": self.get("allowed_users")
        }
