import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.core.orchestrator import AgentOrchestrator


def test_infer_assistive_target_label_strips_style_clause():
    text = "indique na minha tela com uma seta na cor vermelha, onde tem uma aba com titulo frontend"
    label = AgentOrchestrator._infer_assistive_target_label(text)
    assert "aba com titulo frontend" in label
    assert "seta" not in label


def test_infer_assistive_target_label_rejects_retry_phrase():
    label = AgentOrchestrator._infer_assistive_target_label("tenta novamente")
    assert label == "elemento solicitado na tela"


def test_extract_assistive_render_preferences_arrow_red():
    prefs = AgentOrchestrator._extract_assistive_render_preferences(
        "me mostra com uma seta vermelha onde fica a aba frontend"
    )
    assert prefs.get("mark_type") == "arrow"
    assert prefs.get("color") == "#FF3B30"
