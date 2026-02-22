from types import SimpleNamespace

from server.routes.skills import get_skill_registry
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


def _build_request_with_registry(registry: SkillRegistry, allowed_actions=None):
    access_controller = SimpleNamespace(
        get_allowed_actions=lambda context, reg, cfg: allowed_actions if allowed_actions is not None else reg.list_actions()
    )
    kernel = SimpleNamespace(
        skill_registry=registry,
        config_manager=SimpleNamespace(get=lambda *_args, **_kwargs: {}),
        orchestrator=SimpleNamespace(access_controller=access_controller),
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(kernel=kernel)))


def test_registry_endpoint_uses_contract_metadata_for_object_actions():
    registry = SkillRegistry()
    registry.register(
        DummySkill(
            "web_search",
            "web.search",
            ["discover"],
            contract={
                "actions": {
                    "discover": {
                        "description": "Discover web documents",
                        "risk_level": "low",
                    }
                }
            },
        )
    )

    request = _build_request_with_registry(registry)
    user = SimpleNamespace(username="admin")
    items = get_skill_registry(request=request, user=user)
    assert len(items) == 1
    assert items[0]["id"] == "web.search.discover"
    assert items[0]["description"] == "Discover web documents"
    assert items[0]["risk_level"] == "low"


def test_registry_endpoint_uses_contract_metadata_for_array_actions():
    registry = SkillRegistry()
    registry.register(
        DummySkill(
            "system_control",
            "system.control",
            ["power"],
            contract={
                "actions": [
                    {
                        "id": "system.control.power",
                        "description": "Power control",
                        "risk_level": "high",
                    }
                ]
            },
        )
    )

    request = _build_request_with_registry(registry)
    user = SimpleNamespace(username="admin")
    items = get_skill_registry(request=request, user=user)
    assert len(items) == 1
    assert items[0]["id"] == "system.control.power"
    assert items[0]["description"] == "Power control"
    assert items[0]["risk_level"] == "high"


def test_registry_endpoint_can_filter_by_principal_scope():
    registry = SkillRegistry()
    registry.register(DummySkill("web_search", "web.search", ["discover"]))
    registry.register(DummySkill("shell_control", "shell", ["exec"]))

    request = _build_request_with_registry(registry, allowed_actions=["web.search.discover"])
    user = SimpleNamespace(username="admin")
    items = get_skill_registry(
        request=request,
        interface="web",
        sender_id="user_42",
        session_id="sess-42",
        user=user,
    )
    assert len(items) == 1
    assert items[0]["id"] == "web.search.discover"
