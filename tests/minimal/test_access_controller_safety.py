import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.access_controller import AccessController
from core.identity import AccessStatus, PrincipalContext, UserEntity


class _RegistryMissingMetadata:
    def get_action_metadata(self, action_id):
        return {}


def test_pre_dispatch_gate_fails_closed_when_risk_metadata_missing(tmp_path):
    controller = AccessController(str(tmp_path))
    context = PrincipalContext(
        interface="cli",
        sender_id="user-1",
        session_id="session-1",
        is_group=False,
    )
    user = UserEntity(id="user-1", interface="cli", status=AccessStatus.PENDING)

    controller._resolve_context_entities = lambda _context: (user, None, {"dm_mode": "approved_only"})  # type: ignore[method-assign]

    allowed, reason = controller.pre_dispatch_gate(
        context=context,
        action="os.delete_file",
        params={},
        capability_registry=_RegistryMissingMetadata(),
        config_manager=None,
    )

    assert allowed is False
    assert "alto risco" in reason.lower()


def test_pre_dispatch_gate_fails_closed_when_anyone_metadata_missing(tmp_path):
    controller = AccessController(str(tmp_path))
    context = PrincipalContext(
        interface="cli",
        sender_id="user-1",
        session_id="session-1",
        is_group=False,
    )
    user = UserEntity(id="user-1", interface="cli", status=AccessStatus.PENDING)

    controller._resolve_context_entities = lambda _context: (user, None, {"dm_mode": "anyone"})  # type: ignore[method-assign]

    allowed, reason = controller.pre_dispatch_gate(
        context=context,
        action="tools.safe_action",
        params={},
        capability_registry=_RegistryMissingMetadata(),
        config_manager=None,
    )

    assert allowed is False
    assert "aprovação manual" in reason.lower()
