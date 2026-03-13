import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.orchestrator import AgentOrchestrator, _CapabilitySessionView


class _FakeSession:
    def __init__(self):
        self.session_id = "web-test"
        self.context = {"user_language": "pt-BR"}


def test_capability_session_view_blocks_direct_messaging():
    view = _CapabilitySessionView(_FakeSession())
    assert view.session_id == "web-test"
    assert view.context.get("user_language") == "pt-BR"

    try:
        view.add_message("assistant", "nope")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "not allowed" in str(exc).lower()


def test_capability_callbacks_view_exposes_only_send_status():
    captured = []

    def _send_status(*args, **kwargs):
        captured.append((args, kwargs))

    callbacks = {
        "send_status": _send_status,
        "send_response": lambda *args, **kwargs: None,
        "send_complete": lambda *args, **kwargs: None,
    }
    filtered = AgentOrchestrator._build_capability_callbacks_view(callbacks)

    assert set(filtered.keys()) == {"send_status"}
    filtered["send_status"]("executing", {"action": "x"})
    assert len(captured) == 1
