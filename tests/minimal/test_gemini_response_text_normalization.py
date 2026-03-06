import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.drivers.llm.gemini_driver import GeminiProvider


def test_normalize_response_text_dict_to_string():
    value = {"v": "toon.v1", "t": "session_summary", "data": {"a": 1}}
    out = GeminiProvider._normalize_response_text(value)
    assert isinstance(out, str)
    assert "toon.v1" in out


def test_normalize_response_text_prefers_text_field():
    value = {"text": "ok resumo"}
    out = GeminiProvider._normalize_response_text(value)
    assert out == "ok resumo"
