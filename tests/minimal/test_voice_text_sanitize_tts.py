import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.utils.voice_text import sanitize_tts_text


def test_sanitize_tts_text_replaces_fenced_code_and_url():
    text = "Veja isso:\n```python\nprint('oi')\n```\nAcesse https://example.com/docs"
    out = sanitize_tts_text(text)
    assert "print('oi')" not in out
    assert "https://example.com/docs" not in out
    assert "bloco de código" in out
    assert "link" in out


def test_sanitize_tts_text_replaces_inline_code():
    text = "Use `pip install pacote` antes de continuar."
    out = sanitize_tts_text(text)
    assert "pip install pacote" not in out
    assert "código" in out
