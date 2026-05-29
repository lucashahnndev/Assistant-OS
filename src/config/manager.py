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
        """Loads configuration from file."""
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
                    
                # Strict config loading: no legacy compatibility or silent migration.
                changed = False
                if changed:
                    with open(self.config_file, 'w', encoding='utf-8') as fw:
                        json.dump(data, fw, indent=4)
                        logger.info("Migrated config.json to new Model Pool format.")
                        
                self.config_data = data
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                self.config_data = {}
        else:
            logger.warning(f"Config file not found: {self.config_file}")
            self.config_data = {}

    def get_config(self, key, default=None):
        """Retrieves a configuration value."""
        return self.config_data.get(key, default)

    def get(self, key, default=None):
        """Retrieves a configuration value (alias)."""
        return self.get_config(key, default)

    def get_tts_config(self):
        """Returns TTS specific configuration."""
        return self.get("cortex", {}).get("audio", {}).get("tts", [])

    def get_llm_config(self):
        """Returns LLM specific configuration."""
        return self.get("cortex", {}).get("chat", [])

    def get_telegram_config(self):
        telegram_cfg = self.get_interfaces_config().get("telegram", {})
        return {
            "enabled": bool(telegram_cfg.get("enabled", False)),
            "secret_ref": telegram_cfg.get("secret_ref", ""),
            "allowed_users": telegram_cfg.get("allowed_users", []),
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
                "secret_ref": "",
                "allowed_users": []
            },
            "browser": {
                "enabled": False
            }
        }
        return self.get("interfaces", default_interfaces)

    def get_stt_config(self):
        """Returns STT (Speech-to-Text) configuration."""
        return self.get("cortex", {}).get("audio", {}).get("stt", [])

    def get_vision_config(self):
        """Returns Vision specific configuration."""
        return self.get("cortex", {}).get("vision", [])

    def get_capabilities_config(self):
        """Returns the capabilities enablement configuration."""
        return self.get("capabilities", {})

    def get_capability_config(self, capability_name):
        """Returns configuration for a specific capability."""
        return self.get_capabilities_config().get(capability_name, {})

    def get_agent_config(self):
        """Returns the top-level agent configuration."""
        agent_cfg = self.get("agent", {})
        return agent_cfg if isinstance(agent_cfg, dict) else {}

    def get_intelligence_config(self):
        """Returns model-scoped intelligence configuration overrides."""
        intelligence_cfg = self.get("intelligence", {})
        return intelligence_cfg if isinstance(intelligence_cfg, dict) else {}

    @staticmethod
    def _normalize_tools_discovery_mode(value):
        """Normalizes discovery decision mode aliases to canonical values."""
        mode = str(value or "").strip().lower().replace("-", "_")
        if not mode:
            return ""
        if mode in {"agentic", "agentic_only", "llm", "llm_only"}:
            return "agentic_only"
        if mode in {"hybrid", "deterministic", "deterministic_only", "off", "fallback_only"}:
            return mode
        return ""

    def get_tools_discovery_decision_mode(self, model_name=None, provider=None, model_id=None):
        """
        Returns the tools discovery decision mode with precedence:
        1. intelligence.<model_id>.tools_discovery.decision_mode
        2. intelligence.<model_name>.tools_discovery.decision_mode
        3. intelligence.<provider>.tools_discovery.decision_mode
        4. agent.tools_discovery.decision_mode
        5. decision_policy.tools_discovery.decision_mode
        6. default agentic_only
        """
        intelligence_cfg = self.get_intelligence_config()

        def _lookup(key):
            if not key:
                return ""
            entry = intelligence_cfg.get(str(key), {})
            if not isinstance(entry, dict):
                return ""
            tools_cfg = entry.get("tools_discovery", {})
            if not isinstance(tools_cfg, dict):
                return ""
            return self._normalize_tools_discovery_mode(tools_cfg.get("decision_mode"))

        for candidate in (model_id, model_name, provider):
            normalized = _lookup(candidate)
            if normalized:
                return normalized

        agent_cfg = self.get_agent_config()
        tools_cfg = agent_cfg.get("tools_discovery", {}) if isinstance(agent_cfg, dict) else {}
        if isinstance(tools_cfg, dict):
            normalized = self._normalize_tools_discovery_mode(tools_cfg.get("decision_mode"))
            if normalized:
                return normalized

        decision_policy = self.get("decision_policy", {})
        if isinstance(decision_policy, dict):
            tools_cfg = decision_policy.get("tools_discovery", {})
            if isinstance(tools_cfg, dict):
                normalized = self._normalize_tools_discovery_mode(tools_cfg.get("decision_mode"))
                if normalized:
                    return normalized

        return "agentic_only"

    def get_mcp_config(self):
        """Returns generic MCP client/server integration configuration."""
        default_mcp = {
            "enabled": False,
            "servers": [],
        }
        return self.get("mcp", default_mcp)

    def get_location_config(self):
        """Returns location specific configuration."""
        default_loc = {
            "mode": "auto",
            "default": {
                "city": "Unknown",
                "timezone": "UTC",
                "language": "en",
                "latitude": 0.0,
                "longitude": 0.0
            }
        }
        return self.get("location", default_loc)

    def get_timezone(self) -> str:
        """Returns the configured timezone, falling back to UTC."""
        location_cfg = self.get_location_config()
        # default_loc is already nested in get_location_config default, but let's be safe
        default_tz = location_cfg.get("default", {}).get("timezone") if isinstance(location_cfg.get("default"), dict) else None
        if not default_tz:
             default_tz = location_cfg.get("timezone") # Flat structure support

        if default_tz:
            return str(default_tz)
        
        env_tz = self.get("environment", {}).get("timezone")
        if env_tz:
            return str(env_tz)
            
        return "UTC"

    def get_i18n_config(self):
        """Returns i18n/language configuration."""
        default_i18n = {
            "default_locale": "en",
            "fallback_locale": "en",
            "supported_locales": ["en", "pt-BR"],
        }
        return self.get("i18n", default_i18n)
