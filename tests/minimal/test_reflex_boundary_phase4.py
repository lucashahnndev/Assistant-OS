import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.core.reflex.registry import ReflexRegistry
from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability
from src.capabilities.calendar.runtime import CalendarCapability
from src.capabilities.notifications.capability import NotificationCapability
from src.capabilities.system_control.capability import SystemCapability


class _Kernel:
    def __init__(self):
        self.orchestrator = type("_Orchestrator", (), {"calendar_service": object()})()
        self.calendar_service = self.orchestrator.calendar_service


def test_phase4_reflex_boundary_keeps_only_operational_paths():
    system = SystemCapability(kernel=None, config={})
    browser = BrowserControlCapability(kernel=None, config={})
    calendar = CalendarCapability(kernel=_Kernel(), config={})
    notifications = NotificationCapability(kernel=None, config={})

    assert system.get_reflex_rules()
    assert browser.get_reflex_rules() == []
    assert notifications.get_reflex_rules() == []

    registry = ReflexRegistry()
    for rule in calendar.get_reflex_rules():
        registry.register(rule["pattern"], rule["action_id"], handler=rule.get("handler"))
    for rule in system.get_reflex_rules():
        registry.register(rule["pattern"], rule["action_id"], handler=rule.get("handler"))

    assert registry.match("[INTERNAL_EVENT] Type: calendar.event_starting Payload: {'title': 'Demo', 'event_id': 'e1', 'start_time': '123'}") is not None
    assert registry.match("/status work-1") is not None
    assert registry.match("/cancel work-1") is not None
    assert registry.match("me mostra na tela o telegram") is None
    assert registry.match("abre o navegador agora") is None
    assert registry.match("não me mande mais push") is None
