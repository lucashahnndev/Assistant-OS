from core.orchestrator import AgentOrchestrator
from skills.base import SkillBase
from skills.registry import SkillRegistry


class _DummySkill(SkillBase):
    def __init__(self, name: str, namespace: str, actions: list[str]):
        self._name = name
        self._namespace = namespace
        self._actions = actions

    @property
    def name(self) -> str:
        return self._name

    @property
    def actions(self) -> list[str]:
        return self._actions

    def execute(self, action_id, params, context):
        return {"ok": True}


def test_registry_resolve_action_id_supports_local_and_typo_forms():
    registry = SkillRegistry()
    registry.register(_DummySkill("web", "web.search", ["discover"]))
    registry.register(_DummySkill("system", "system.control", ["process.kill"]))

    assert registry.resolve_action_id("web.search.discover") == "web.search.discover"
    assert registry.resolve_action_id("discover") == "web.search.discover"
    assert registry.resolve_action_id("system.control.proces.kill") == "system.control.process.kill"


def test_registry_suggest_actions_returns_candidates():
    registry = SkillRegistry()
    registry.register(_DummySkill("web", "web.search", ["discover"]))
    registry.register(_DummySkill("system", "system.control", ["process.kill"]))

    suggestions = registry.suggest_actions("system.control.process.kil", limit=2)
    assert "system.control.process.kill" in suggestions


def test_assess_action_result_classifies_errors_and_success():
    status_fail, reason_fail = AgentOrchestrator._assess_action_result("Error executing shell.execute: boom")
    status_ok, reason_ok = AgentOrchestrator._assess_action_result("Comando executado com sucesso.")

    assert status_fail == "failure"
    assert reason_fail in {"failure_marker_detected", "explicit_error_prefix"}
    assert status_ok == "success"
    assert reason_ok == "ok"


def test_assess_action_result_understands_structured_payloads():
    status_error, reason_error = AgentOrchestrator._assess_action_result({"ok": False, "status": "error", "error": "MISSING_QUERY"})
    status_empty, reason_empty = AgentOrchestrator._assess_action_result({"ok": True, "status": "empty", "results": []})
    status_success, reason_success = AgentOrchestrator._assess_action_result({"ok": True, "status": "success"})

    assert status_error == "failure"
    assert reason_error == "MISSING_QUERY"
    assert status_empty == "success"
    assert reason_empty == "empty"
    assert status_success == "success"
    assert reason_success == "success"


def test_ground_reply_blocks_false_success_claim_after_failure():
    grounded = AgentOrchestrator._ground_reply_against_last_result(
        response_text="Pronto, concluído com sucesso.",
        last_action_status="failure",
        last_action_id="shell.control.execute",
        last_action_reason="failure_marker_detected",
        last_action_output="Error executing shell.execute: boom",
    )

    lower = grounded.lower()
    assert ("falhou" in lower) or ("failed" in lower)
    assert "shell.control.execute" in grounded
    assert grounded != "Pronto, concluído com sucesso."


def test_ground_reply_keeps_honest_failure_message():
    original = "Não consegui concluir porque houve erro no comando."
    grounded = AgentOrchestrator._ground_reply_against_last_result(
        response_text=original,
        last_action_status="failure",
        last_action_id="shell.control.execute",
        last_action_reason="failure_marker_detected",
        last_action_output="Error executing shell.execute: boom",
    )

    assert grounded == original


def test_reply_from_last_success_localizes_header_for_ptbr():
    reply = AgentOrchestrator._reply_from_last_success(
        action_id="web.search.discover",
        structured_result={
            "results": [
                {"title": "Resultado A", "url": "https://example.com/a"},
                {"title": "Resultado B", "url": "https://example.com/b"},
            ]
        },
        raw_output="",
        language="pt-BR",
    )

    assert isinstance(reply, str)
    assert reply.startswith("Encontrei estes resultados:")
