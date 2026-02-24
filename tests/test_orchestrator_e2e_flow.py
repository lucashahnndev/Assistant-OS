import os

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
    lowered = result.lower()
    assert ("falhou" in lowered) or ("could not complete" in lowered) or ("failed" in lowered)
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


def test_scheduled_global_transient_runtime_does_not_persist_session(tmp_path, monkeypatch):
    orchestrator = _fresh_orchestrator(tmp_path, monkeypatch)

    runtime_session_id = "global-task-t001-abcd1234"
    result = orchestrator.process(
        user_input="Execute task 'Global Task': run checks",
        session_id=runtime_session_id,
        user_data={"origin": "scheduled", "transient_session": True},
        initial_plan=ActionPlan(
            action_id="reply",
            args={},
            confidence=1.0,
            source="internal",
            response_text="Global task completed.",
            thought="Transient runtime response",
        ),
    )

    assert "Global task completed." in result
    assert runtime_session_id not in orchestrator.sessions
    persisted_path = os.path.join(orchestrator.sessions_dir, runtime_session_id, "session.json")
    assert os.path.exists(persisted_path) is False


def test_worker_run_does_not_create_missing_session(tmp_path, monkeypatch):
    orchestrator = _fresh_orchestrator(tmp_path, monkeypatch)
    missing_session_id = "missing-worker-parent"

    result = orchestrator.process(
        user_input="run worker task",
        session_id=missing_session_id,
        user_data={"__worker_run": True},
        initial_plan=ActionPlan(
            action_id="reply",
            args={},
            confidence=1.0,
            source="internal",
            response_text="This should not run.",
            thought="Worker should fail before creating session.",
        ),
    )

    assert "worker" in result.lower()
    assert missing_session_id not in orchestrator.sessions
    persisted_path = os.path.join(orchestrator.sessions_dir, missing_session_id, "session.json")
    assert os.path.exists(persisted_path) is False


def test_enforce_response_language_normalizes_common_mixed_fragments(tmp_path, monkeypatch):
    orchestrator = _fresh_orchestrator(tmp_path, monkeypatch)
    session = orchestrator.create_session("lang-pt", interface="web")
    session.context["user_language"] = "pt-BR"

    mixed = "Agora em Canoas faz 27°C. Feels like: 29°C. Would you like me to proceed with the next practical step?"
    normalized = orchestrator._enforce_response_language(session, mixed)

    assert "Feels like:" not in normalized
    assert "Would you like me" not in normalized
    assert "Sensação térmica:" in normalized
