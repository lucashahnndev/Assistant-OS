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
                    
                # Migrate config to new Model Pool format if needed
                data, changed = self._migrate_config(data)
                data, legacy_changed = self._migrate_browser_legacy_keys(data)
                changed = changed or legacy_changed
                if changed:
                    with open(self.config_file, 'w', encoding='utf-8') as fw:
                        json.dump(data, fw, indent=4)
                        logger.info("Migrated config.json to new Model Pool format.")
                        
                self.config_data = self._substitute_env_vars(data)
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                self.config_data = {}
        else:
            logger.warning(f"Config file not found: {self.config_file}")
            self.config_data = {}

    def _migrate_browser_legacy_keys(self, data):
        changed = False
        if not isinstance(data, dict):
            return data, changed

        skills_cfg = data.get("skills")
        if not isinstance(skills_cfg, dict):
            skills_cfg = {}
            data["skills"] = skills_cfg
            changed = True

        legacy_skill_key = "browser_" + "automator"
        mapped_skill_key = "browser_" + "control"
        legacy = skills_cfg.get(legacy_skill_key)
        if isinstance(legacy, dict):
            logger.warning("Legacy browser skill config key detected. Mapping to browser.control and disabling legacy skill.")
            control = skills_cfg.get(mapped_skill_key)
            if not isinstance(control, dict):
                control = {}
                skills_cfg[mapped_skill_key] = control
                changed = True
            st = control.get("step_timeout_ms")
            if not isinstance(st, dict):
                st = {}
            timeout_ms = int(legacy.get("timeoutMs") or 30000)
            st.setdefault("go", timeout_ms)
            st.setdefault("ck", 10000)
            st.setdefault("tp", 10000)
            st.setdefault("ss", 5000)
            st.setdefault("perceive", 10000)
            control["step_timeout_ms"] = st
            control.setdefault("enabled", True)
            legacy["enabled"] = False
            changed = True

        # Guard against root-level legacy keys.
        legacy_root_keys = ("browser_" + "automator", "browser." + "automator")
        for key in legacy_root_keys:
            if key in data:
                logger.warning("Legacy browser key detected at root: %s (ignored).", key)
                data.pop(key, None)
                changed = True

        return data, changed

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
                "huggingface": {
                    "api_key": "",
                    "model": "HuggingFaceTB/SmolLM3-3B",
                    "base_url": "https://router.huggingface.co/v1"
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
                "wake_word": "assistant"
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
                },
                "huggingface": {
                    "api_key": "",
                    "model": "Qwen/Qwen2.5-VL-7B-Instruct",
                    "base_url": "https://router.huggingface.co/v1"
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

    def get_i18n_config(self):
        """Returns i18n/language configuration."""
        default_i18n = {
            "default_locale": "en",
            "fallback_locale": "en",
            "supported_locales": ["en", "pt-BR"],
        }
        return self.get("i18n", default_i18n)

    def _migrate_config(self, data):
        """
        Migrates the configuration data from the legacy dictionary format
        to the new array-based Model Pool format.
        It also moves any inline API keys to the .env file and replaces
        them with reference pointers prefixed with ENV_.
        """
        changed = False
        import hashlib
        
        env_path = os.path.join(self.base_data_dir, '.env')
        env_updates = {}
        
        def _get_or_create_env_ref(secret_value, provider_name, field_name):
            if not secret_value: return ""
            if isinstance(secret_value, str) and secret_value.startswith("ENV_"):
                return secret_value
            # Generate new env variable name
            hash_suffix = hashlib.md5(secret_value.encode()).hexdigest()[:6].upper()
            env_name = f"{provider_name.upper()}_{field_name.upper()}_{hash_suffix}"
            env_ref = f"ENV_{env_name}"
            env_updates[env_name] = secret_value
            return env_ref
            
        def _migrate_modality(old_data):
            # If it's already a list, it's migrated
            if isinstance(old_data, list):
                return old_data, False
            if not isinstance(old_data, dict) or "providers" not in old_data:
                return old_data, False
            
            pool = []
            primary = old_data.get("provider", "")
            priority = 1
            
            # Map old dict to new Array Pool
            for prov_name, prov_cfg in old_data.get("providers", {}).items():
                inst = {
                    "id": f"{prov_name}-1",
                    "provider": prov_name,
                    "enabled": True,
                    "priority": 1 if prov_name == primary else priority + 1
                }
                
                if isinstance(prov_cfg, dict):
                    import copy
                    cfg_copy = copy.deepcopy(prov_cfg)
                    # Extract secrets
                    for k in ["api_key", "token", "organization_id", "client_secret"]:
                        if k in cfg_copy:
                            val = cfg_copy.pop(k, "")
                            if val:
                                inst[f"{k}_ref"] = _get_or_create_env_ref(val, prov_name, k)
                    
                    # Merge remaining config
                    inst.update(cfg_copy)
                    
                pool.append(inst)
                priority += 1
                
            # sort by priority
            pool.sort(key=lambda x: x["priority"])
            return pool, True

        cortex = data.get("cortex", {})
        cortex_changed = False
        
        if "chat" in cortex:
            new_chat, c = _migrate_modality(cortex["chat"])
            if c:
                cortex["chat"] = new_chat
                cortex_changed = True
                
        if "vision" in cortex:
            new_vision, c = _migrate_modality(cortex["vision"])
            if c:
                cortex["vision"] = new_vision
                cortex_changed = True
                
        if "audio" in cortex:
            audio = cortex["audio"]
            if "stt" in audio:
                new_stt, c = _migrate_modality(audio["stt"])
                if c:
                    audio["stt"] = new_stt
                    cortex_changed = True
            if "tts" in audio:
                new_tts, c = _migrate_modality(audio["tts"])
                if c:
                    audio["tts"] = new_tts
                    cortex_changed = True
                    
        if cortex_changed:
            data["cortex"] = cortex
            changed = True
            
        if changed and env_updates:
            # write new env variables to .env
            mode = 'a' if os.path.exists(env_path) else 'w'
            try:
                with open(env_path, mode, encoding='utf-8') as fe:
                    fe.write("\n# Migrated Keys\n")
                    for k, v in env_updates.items():
                        fe.write(f"{k}={v}\n")
                logger.info(f"Migrated secrets and saved to {env_path}")
            except Exception as e:
                logger.error(f"Failed to append to .env during migration: {e}")
                    
        return data, changed
