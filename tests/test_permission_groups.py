import tempfile

from core.access_controller import AccessController
from core.identity import PermissionGroup, PrincipalContext
from skills.base import SkillBase
from skills.registry import SkillRegistry


class DummySkill(SkillBase):
    def __init__(self, skill_name: str, namespace: str, actions: list[str], contract: dict | None = None):
        self._name = skill_name
        self._namespace = namespace
        self._actions = actions
        self._contract = contract or {}

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


def _registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(
        DummySkill(
            "web_search",
            "web.search",
            ["discover"],
            contract={"actions": {"discover": {"description": "search web", "risk_level": "low"}}},
        )
    )
    registry.register(
        DummySkill(
            "system_control",
            "system.control",
            ["power"],
            contract={"actions": [{"id": "system.control.power", "name": "power", "risk_level": "high"}]},
        )
    )
    return registry


def test_web_user_bootstrap_group_is_master():
    with tempfile.TemporaryDirectory() as data_dir:
        access = AccessController(data_dir)
        ctx = PrincipalContext(interface="web", sender_id="user_alpha", session_id="web-s1")

        ok, _ = access.pre_llm_gate(ctx)
        user = access.identity_service.get_user("web", "user_alpha")

        assert ok is True
        assert user is not None
        assert user.group_id == "master"


def test_group_allow_list_controls_actions_without_per_user_skill_matrix():
    registry = _registry()
    config = DummyConfig({"web_search": {"enabled": True}, "system_control": {"enabled": True}})

    with tempfile.TemporaryDirectory() as data_dir:
        access = AccessController(data_dir)
        access.identity_service.save_permission_group(
            PermissionGroup(
                id="reader",
                name="Reader",
                allow_actions=["web.search.discover"],
                deny_actions=[],
                allow_skills=[],
                deny_skills=[],
            )
        )

        ctx = PrincipalContext(interface="web", sender_id="user_reader", session_id="web-s2")
        access.pre_llm_gate(ctx)
        user = access.identity_service.get_user("web", "user_reader")
        user.group_id = "reader"
        access.identity_service.save_user(user)

        allowed = access.get_allowed_actions(ctx, registry, config)
        ok_web, _ = access.pre_dispatch_gate(ctx, "web.search.discover", {}, registry, config)
        ok_power, reason_power = access.pre_dispatch_gate(ctx, "system.control.power", {}, registry, config)

        assert allowed == ["web.search.discover"]
        assert ok_web is True
        assert ok_power is False
        assert "não está permitida" in reason_power


def test_interface_auto_approve_group_assignment_is_applied_for_new_users():
    with tempfile.TemporaryDirectory() as data_dir:
        access = AccessController(data_dir)

        policy = access.identity_service.policy
        policy["interfaces"]["web"]["auto_approve_user_group"] = "medium"
        access.identity_service.save_policy()

        ctx = PrincipalContext(interface="web", sender_id="user_medium", session_id="web-s3")
        access.pre_llm_gate(ctx)
        user = access.identity_service.get_user("web", "user_medium")

        assert user is not None
        assert user.group_id == "medium"


def test_master_group_wildcard_still_includes_new_actions():
    registry = _registry()
    config = DummyConfig({"web_search": {"enabled": True}, "system_control": {"enabled": True}})

    with tempfile.TemporaryDirectory() as data_dir:
        access = AccessController(data_dir)
        ctx = PrincipalContext(interface="web", sender_id="user_master", session_id="web-s4")
        access.pre_llm_gate(ctx)

        allowed = access.get_allowed_actions(ctx, registry, config)
        assert "web.search.discover" in allowed
        assert "system.control.power" in allowed


def test_default_groups_include_wikipedia_permissions():
    with tempfile.TemporaryDirectory() as data_dir:
        access = AccessController(data_dir)
        medium = access.identity_service.get_permission_group("medium")
        critical = access.identity_service.get_permission_group("critical")

        assert medium is not None
        assert critical is not None
        assert "wikipedia.*" in medium.allow_actions
        assert "wikipedia.search" in critical.allow_actions


def test_legacy_validator_interface_is_mapped_to_cli():
    with tempfile.TemporaryDirectory() as data_dir:
        access = AccessController(data_dir)

        assert "cli" in access.identity_service.policy["interfaces"]
        assert "validator" not in access.identity_service.policy["interfaces"]

        ctx = PrincipalContext(interface="validator", sender_id="legacy-user", session_id="cli-s1")
        ok, _ = access.pre_llm_gate(ctx)
        user = access.identity_service.get_user("cli", "legacy-user")

        assert ok is True
        assert user is not None
        assert user.interface == "cli"
