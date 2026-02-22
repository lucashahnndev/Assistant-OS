from core.identity import PrincipalContext
from core.orchestrator import AgentOrchestrator
from core.resolution.action_plan import ActionPlan
from config.manager import ConfigManager


def _fresh_orchestrator(tmp_path, monkeypatch) -> AgentOrchestrator:
    data_dir = tmp_path / "aosd-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AOSD_DATA_DIR", str(data_dir))

    # Reset singleton instances to isolate test state.
    ConfigManager._instance = None
    AgentOrchestrator._instance = None
    orchestrator = AgentOrchestrator()
    orchestrator.location_service.get_current_location = lambda ctx=None: {"city": "Testville"}
    return orchestrator


def test_e2e_resolves_typo_action_before_dispatch(tmp_path, monkeypatch):
    orchestrator = _fresh_orchestrator(tmp_path, monkeypatch)

    dispatched_actions: list[str] = []

    def fake_dispatch(action_id, params, context):
        dispatched_actions.append(action_id)
        return {"ok": True}

    def resolve_reply(user_input, context):
        return ActionPlan(
            action_id="reply",
            args={},
            confidence=0.99,
            source="llm",
            response_text="Busca concluída.",
            thought="Done",
        )

    monkeypatch.setattr(orchestrator.skill_registry, "dispatch", fake_dispatch)
    monkeypatch.setattr(orchestrator.intent_resolver_chain, "resolve", resolve_reply)

    result = orchestrator.process(
        user_input="pesquise algo",
        session_id="e2e-typo-action",
        initial_plan=ActionPlan(
            action_id="web.search.discovr",
            args={"query": "python"},
            confidence=0.98,
            source="llm",
            thought="Execute search",
        ),
    )

    assert dispatched_actions
    assert dispatched_actions[0] == "web.search.discover"
    assert "Busca concluída." in result


def test_e2e_denied_action_cannot_end_as_fake_success(tmp_path, monkeypatch):
    orchestrator = _fresh_orchestrator(tmp_path, monkeypatch)

    dispatch_calls = {"count": 0}

    def fake_dispatch(action_id, params, context):
        dispatch_calls["count"] += 1
        return {"ok": True}

    def resolve_reply(user_input, context):
        return ActionPlan(
            action_id="reply",
            args={},
            confidence=0.98,
            source="llm",
            response_text="Concluído com sucesso.",
            thought="Claim success",
        )

    monkeypatch.setattr(orchestrator.skill_registry, "dispatch", fake_dispatch)
    monkeypatch.setattr(orchestrator.intent_resolver_chain, "resolve", resolve_reply)

    principal = PrincipalContext(
        interface="web",
        sender_id="restricted-user",
        sender_name="Restricted",
        session_id="e2e-restricted",
    )
    orchestrator.access_controller.pre_llm_gate(principal)
    user = orchestrator.access_controller.identity_service.get_user("web", "restricted-user")
    user.overrides.allow_actions = ["web.search.discover"]
    orchestrator.access_controller.identity_service.save_user(user)

    result = orchestrator.process(
        user_input="me diga as horas",
        session_id="e2e-restricted",
        context=principal,
        initial_plan=ActionPlan(
            action_id="system.control.time",
            args={},
            confidence=0.98,
            source="llm",
            thought="Try restricted action",
        ),
    )

    assert dispatch_calls["count"] == 0
    assert "falhou" in result.lower()
    assert "system.control.time" in result


def test_e2e_prompt_context_isolated_per_session(tmp_path, monkeypatch):
    orchestrator = _fresh_orchestrator(tmp_path, monkeypatch)

    session_a = orchestrator.create_session("e2e-session-a", interface="web")
    session_b = orchestrator.create_session("e2e-session-b", interface="web")

    session_a.drivers_state = {"browser": {"active_pages": [{"title": "A", "url": "https://a.example"}]}}
    session_b.drivers_state = {"browser": {"active_pages": [{"title": "B", "url": "https://b.example"}]}}

    orchestrator.scratchpad_service.update("NOTA_A", session_id="e2e-session-a")
    orchestrator.scratchpad_service.update("NOTA_B", session_id="e2e-session-b")

    prompt_a = orchestrator._construct_system_prompt(session_a, user_input="abra o browser")
    prompt_b = orchestrator._construct_system_prompt(session_b, user_input="abra o browser")

    assert "https://a.example" in prompt_a
    assert "https://b.example" not in prompt_a
    assert "NOTA_A" in prompt_a
    assert "NOTA_B" not in prompt_a

    assert "https://b.example" in prompt_b
    assert "https://a.example" not in prompt_b
    assert "NOTA_B" in prompt_b
    assert "NOTA_A" not in prompt_b
