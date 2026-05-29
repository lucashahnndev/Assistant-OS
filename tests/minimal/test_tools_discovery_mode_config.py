import json
import sys
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.manager import ConfigManager


def test_tools_discovery_mode_prefers_model_override(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "agent": {
                    "tools_discovery": {
                        "decision_mode": "agentic_only",
                    }
                },
                "intelligence": {
                    "qwen2.5-14b-instruct-q3": {
                        "tools_discovery": {
                            "decision_mode": "deterministic",
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    previous_instance = ConfigManager._instance
    previous_dotenv = sys.modules.get("dotenv")
    try:
        sys.modules["dotenv"] = SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
        ConfigManager._instance = None
        cfg = ConfigManager(config_file=str(config_file))
        assert cfg.get_tools_discovery_decision_mode(model_name="qwen2.5-14b-instruct-q3") == "deterministic"
        assert cfg.get_tools_discovery_decision_mode(model_name="gemini-3.1-flash-lite") == "agentic_only"
        assert cfg.get_tools_discovery_decision_mode() == "agentic_only"
    finally:
        ConfigManager._instance = previous_instance
        if previous_dotenv is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = previous_dotenv
