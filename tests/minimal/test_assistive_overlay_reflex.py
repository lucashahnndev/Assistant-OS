import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.core.reflex.registry import ReflexRegistry
from src.capabilities.assistive_overlay.capability import AssistiveOverlayCapability


def test_reflex_shortcuts_disabled_by_default():
    capability = AssistiveOverlayCapability(kernel=None, config={"backend": "noop"})
    assert capability.get_reflex_rules() == []


def test_reflex_shortcuts_do_not_route_natural_language_to_overlay():
    capability = AssistiveOverlayCapability(kernel=None, config={"overlay": {"backend": "noop", "enable_reflex_shortcuts": True}})
    registry = ReflexRegistry()
    for rule in capability.get_reflex_rules():
        registry.register(rule["pattern"], rule["action_id"], handler=rule.get("handler"))

    text = "atlas, me mostra na minha tela a guia que está aberta para o telegram"
    plan = registry.match(text)

    assert plan is None
