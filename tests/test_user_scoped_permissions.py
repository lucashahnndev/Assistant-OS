import tempfile

from core.access_controller import AccessController
from core.identity import AccessStatus, PrincipalContext
from core.session import Session
from services.safety_service import SafetyService
from skills.base import SkillBase
from skills.registry import SkillRegistry
from skills.task_management.skill import TaskSkill


class DummySkill(SkillBase):
    def __init__(self, skill_name: str, namespace: str, action_names: list[str]):
        self._name = skill_name
        self._namespace = namespace
        self._actions = action_names

    @property
    def name(self) -> str:
        return self._name

    @property
    def actions(self) -> list[str]:
        return self._actions

    def execute(self, action_id, params, context):
        return f"ok:{action_id}"


class DummyConfig:
    def __init__(self, skills_cfg: dict):
        self._skills_cfg = skills_cfg

    def get(self, key, default=None):
        if key == "skills":
            return self._skills_cfg
        return default


def _build_registry() -> SkillRegistry:
    registry = SkillRegistry()
    web = DummySkill("web_search", "web.search", ["discover"])
    web._contract = {
        "actions": {
            "discover": {
                "description": "Discover web content",
                "risk_level": "low",
            }
        }
    }
    registry.register(web)

    system = DummySkill("system_control", "system.control", ["power"])
    system._contract = {
        "actions": [
            {
                "id": "system.control.power",
                "name": "power",
                "description": "Power control",
                "risk_level": "high",
            }
        ]
    }
    registry.register(system)
    return registry


def _create_context(user_id: str) -> PrincipalContext:
    return PrincipalContext(
        interface="web",
        sender_id=user_id,
        sender_name="User",
        session_id=f"session-{user_id}",
    )


def test_get_allowed_actions_respects_user_allow_list_and_skill_enablement():
    registry = _build_registry()
    config = DummyConfig(
        {
            "web_search": {"enabled": True},
            "system_control": {"enabled": False},
        }
    )

    with tempfile.TemporaryDirectory() as data_dir:
        access = AccessController(data_dir)
        ctx = _create_context("allow-list-user")
        access.pre_llm_gate(ctx)

        user = access.identity_service.get_user("web", "allow-list-user")
        user.overrides.allow_actions = ["web.search.discover"]
        access.identity_service.save_user(user)

        allowed = access.get_allowed_actions(ctx, registry, config)

        assert allowed == ["web.search.discover"]
        assert "system.control.power" not in allowed


def test_pre_dispatch_gate_enforces_user_allow_list():
    registry = _build_registry()
    config = DummyConfig(
        {
            "web_search": {"enabled": True},
            "system_control": {"enabled": True},
        }
    )

    with tempfile.TemporaryDirectory() as data_dir:
        access = AccessController(data_dir)
        ctx = _create_context("dispatch-user")
        access.pre_llm_gate(ctx)

        user = access.identity_service.get_user("web", "dispatch-user")
        user.overrides.allow_actions = ["web.search.discover"]
        access.identity_service.save_user(user)

        ok_allowed, _ = access.pre_dispatch_gate(
            ctx, "web.search.discover", {}, registry, config
        )
        blocked_allowed, reason = access.pre_dispatch_gate(
            ctx, "system.control.power", {}, registry, config
        )

        assert ok_allowed is True
        assert blocked_allowed is False
        assert "não está permitida" in reason


def test_task_notes_uses_session_id_for_scratchpad_scope():
    class DummyScratchpad:
        def __init__(self):
            self.last_session_id = None

        def read(self, session_id=None):
            self.last_session_id = session_id
            return "notes-content"

    class DummyOrchestrator:
        def __init__(self):
            self.scratchpad_service = DummyScratchpad()

    class DummyKernel:
        def __init__(self):
            self.orchestrator = DummyOrchestrator()

    skill = TaskSkill(kernel=DummyKernel())
    session = Session("session-xyz")

    result = skill.execute("task.notes", {"command": "read"}, {"session": session})

    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert result.get("content") == "notes-content"
    assert skill.kernel.orchestrator.scratchpad_service.last_session_id == "session-xyz"


def test_pre_dispatch_gate_blocks_unapproved_user_on_contract_high_risk_action():
    registry = _build_registry()
    config = DummyConfig(
        {
            "web_search": {"enabled": True},
            "system_control": {"enabled": True},
        }
    )

    with tempfile.TemporaryDirectory() as data_dir:
        access = AccessController(data_dir)
        ctx = _create_context("pending-user")
        access.pre_llm_gate(ctx)

        user = access.identity_service.get_user("web", "pending-user")
        user.status = AccessStatus.PENDING
        access.identity_service.save_user(user)

        allowed, reason = access.pre_dispatch_gate(
            ctx, "system.control.power", {}, registry, config
        )

        assert allowed is False
        assert ("alto risco" in reason) or ("High Risk" in reason)


def test_safety_service_uses_contract_risk_metadata():
    registry = _build_registry()
    safety = SafetyService()

    assert safety.is_sensitive("system.control.power", {}, registry) is True
    assert safety.is_sensitive("web.search.discover", {}, registry) is False
