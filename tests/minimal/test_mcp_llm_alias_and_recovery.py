import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.core.orchestrator import AgentOrchestrator
from src.core.resolution.llm_resolver import LLMResolver


class _LLMManagerStub:
    def __init__(self, intent):
        self._intent = intent

    def get_active_config(self):
        return {"max_context": 8000}

    def generate_intent(self, *args, **kwargs):
        return self._intent


class _RegistryStub:
    def __init__(self):
        self.aliases = {
            "obsidian.note.create": "obsidian.obsidian.create_note",
            "obsidian.create.note": "obsidian.obsidian.create_note",
        }
        self._actions = {
            "obsidian.obsidian.create_note": {
                "origin": "mcp",
                "server_id": "obsidian",
                "capability_id": "mcp.obsidian",
                "handler": "create_note",
                "namespace": "obsidian.obsidian",
                "aliases": [
                    "obsidian.note.create",
                    "obsidian.create.note",
                    "obsidian.create_note",
                ],
            }
        }

    def resolve_action_id(self, action_id):
        return self.aliases.get(str(action_id or "").strip().lower())

    def get_capability_for_action(self, action_id):
        if str(action_id or "").strip().lower() == "obsidian.obsidian.create_note":
            return object()
        return None

    def list_actions(self):
        return list(self._actions.keys())

    def get_action_metadata(self, action_id):
        return dict(self._actions.get(str(action_id or "").strip().lower(), {}))


def test_llm_resolver_canonicalizes_mcp_alias_before_scoring():
    intent = SimpleNamespace(
        action="obsidian.note.create",
        params={"path": "Batata.md", "content": "oi"},
        response_text="",
        thought="create note",
        attachments=[],
        model_used="stub",
        plan=[],
        state_summary={},
        task_label="",
    )
    resolver = LLMResolver(
        llm_manager=_LLMManagerStub(intent),
        capability_registry=_RegistryStub(),
    )
    session = SimpleNamespace(get_context_for_llm=lambda *args, **kwargs: "")

    plan = resolver.resolve(
        "crie uma nota no obsidian",
        {
            "session": session,
            "allowed_actions": ["obsidian.obsidian.create_note"],
            "capability_registry": _RegistryStub(),
            "history": "",
            "system_prompt": "",
        },
    )

    assert plan is not None
    assert plan.action_id == "obsidian.obsidian.create_note"


def test_llm_resolver_routes_generic_file_write_to_obsidian_create_note():
    intent = SimpleNamespace(
        action="system.file.write",
        params={"path": "Teste MCP.md", "content": "funcionou"},
        response_text="",
        thought="create note",
        attachments=[],
        model_used="stub",
        plan=[],
        state_summary={},
        task_label="",
    )
    resolver = LLMResolver(
        llm_manager=_LLMManagerStub(intent),
        capability_registry=_RegistryStub(),
    )
    session = SimpleNamespace(get_context_for_llm=lambda *args, **kwargs: "")

    plan = resolver.resolve(
        "crie uma nota no obsidian chamada Teste MCP com o texto funcionou",
        {
            "session": session,
            "allowed_actions": ["obsidian.obsidian.create_note"],
            "capability_registry": _RegistryStub(),
            "history": "",
            "system_prompt": "",
        },
    )

    assert plan is not None
    assert plan.action_id == "obsidian.obsidian.create_note"
    assert plan.metadata.get("confidence_notes") is not None


def test_llm_resolver_routes_generic_note_request_to_obsidian_without_explicit_mention():
    intent = SimpleNamespace(
        action="system.file.write",
        params={"path": "Teste MCP.md", "content": "funcionou"},
        response_text="",
        thought="create note",
        attachments=[],
        model_used="stub",
        plan=[],
        state_summary={},
        task_label="",
    )
    resolver = LLMResolver(
        llm_manager=_LLMManagerStub(intent),
        capability_registry=_RegistryStub(),
    )
    session = SimpleNamespace(get_context_for_llm=lambda *args, **kwargs: "")

    plan = resolver.resolve(
        "crie uma nota chamada Teste MCP com o texto funcionou",
        {
            "session": session,
            "allowed_actions": ["obsidian.obsidian.create_note"],
            "capability_registry": _RegistryStub(),
            "history": "",
            "system_prompt": "",
        },
    )

    assert plan is not None
    assert plan.action_id == "obsidian.obsidian.create_note"


def test_llm_resolver_normalizes_allowed_aliases_for_obsidian_write():
    intent = SimpleNamespace(
        action="system.file.write",
        params={"path": "Teste MCP.md", "content": "funcionou"},
        response_text="",
        thought="create note",
        attachments=[],
        model_used="stub",
        plan=[],
        state_summary={},
        task_label="",
    )
    resolver = LLMResolver(
        llm_manager=_LLMManagerStub(intent),
        capability_registry=_RegistryStub(),
    )
    session = SimpleNamespace(get_context_for_llm=lambda *args, **kwargs: "")

    plan = resolver.resolve(
        "crie uma nota no obsidian chamada Teste MCP com o texto funcionou",
        {
            "session": session,
            "allowed_actions": ["obsidian.note.create"],
            "capability_registry": _RegistryStub(),
            "history": "",
            "system_prompt": "",
        },
    )

    assert plan is not None
    assert plan.action_id == "obsidian.obsidian.create_note"


def test_llm_resolver_respects_empty_allowed_actions_as_denied_scope():
    intent = SimpleNamespace(
        action="system.file.write",
        params={"path": "Teste MCP.md", "content": "funcionou"},
        response_text="",
        thought="create note",
        attachments=[],
        model_used="stub",
        plan=[],
        state_summary={},
        task_label="",
    )
    resolver = LLMResolver(
        llm_manager=_LLMManagerStub(intent),
        capability_registry=_RegistryStub(),
    )
    session = SimpleNamespace(get_context_for_llm=lambda *args, **kwargs: "")

    plan = resolver.resolve(
        "crie uma nota no obsidian chamada Teste MCP com o texto funcionou",
        {
            "session": session,
            "allowed_actions": [],
            "capability_registry": _RegistryStub(),
            "history": "",
            "system_prompt": "",
        },
    )

    assert plan is not None
    assert plan.action_id == "error"


def test_recovery_reply_without_tool_data_does_not_claim_success():
    dummy = SimpleNamespace(
        llm_manager=SimpleNamespace(generate_text=lambda *args, **kwargs: "I'm attempting to create a file named teste.txt."),
        _session_locale=lambda _session: "pt-br",
        _t=lambda _session, key, **kwargs: key,
        _looks_like_unverified_progress_claim=AgentOrchestrator._looks_like_unverified_progress_claim,
        _looks_like_success_claim=AgentOrchestrator._looks_like_success_claim,
        _looks_like_guidance_only_reply=AgentOrchestrator._looks_like_guidance_only_reply,
        _sanitize_user_facing_response=AgentOrchestrator._sanitize_user_facing_response,
    )
    session = SimpleNamespace(session_id="test-session", context={}, get_context_for_llm=lambda *args, **kwargs: "")

    reply = AgentOrchestrator._generate_recovery_reply(
        dummy,
        session=session,
        user_input="crie uma nota",
        reason="no_plan_resolved",
        last_tool_data=None,
        last_action_id="obsidian.obsidian.create_note",
    )

    assert "attempting" not in reply.lower()
    assert "estou tentando" not in reply.lower()
    assert reply == ""
    assert session.context.get("last_recovery_sanitization", {}).get("reason_code") == "no_fresh_tool_evidence"


def test_recovery_reply_without_tool_data_does_not_claim_completion():
    dummy = SimpleNamespace(
        llm_manager=SimpleNamespace(
            generate_text=lambda *args, **kwargs: "I've created the `teste.txt` file with \"123\" inside for you, and it's now saved in your Videos folder."
        ),
        _session_locale=lambda _session: "en",
        _t=lambda _session, key, **kwargs: key,
        _looks_like_unverified_progress_claim=AgentOrchestrator._looks_like_unverified_progress_claim,
        _looks_like_success_claim=AgentOrchestrator._looks_like_success_claim,
        _looks_like_guidance_only_reply=AgentOrchestrator._looks_like_guidance_only_reply,
        _sanitize_user_facing_response=AgentOrchestrator._sanitize_user_facing_response,
    )
    session = SimpleNamespace(session_id="test-session", context={}, get_context_for_llm=lambda *args, **kwargs: "")

    reply = AgentOrchestrator._generate_recovery_reply(
        dummy,
        session=session,
        user_input="write a file",
        reason="no_plan_resolved",
        last_tool_data=None,
        last_action_id="system.control.fs.write",
    )

    assert "created" not in reply.lower()
    assert "saved" not in reply.lower()
    assert "execution confirmation" in reply.lower()
    assert session.context.get("last_recovery_sanitization", {}).get("reason_code") == "no_fresh_tool_evidence"


def test_recovery_reply_without_tool_data_is_labeled_as_guidance():
    dummy = SimpleNamespace(
        llm_manager=SimpleNamespace(generate_text=lambda *args, **kwargs: "Here is a concise suggestion: use the relevant tool."),
        _session_locale=lambda _session: "en",
        _t=lambda _session, key, **kwargs: key,
        _looks_like_unverified_progress_claim=AgentOrchestrator._looks_like_unverified_progress_claim,
        _looks_like_success_claim=AgentOrchestrator._looks_like_success_claim,
        _looks_like_guidance_only_reply=AgentOrchestrator._looks_like_guidance_only_reply,
        _sanitize_user_facing_response=AgentOrchestrator._sanitize_user_facing_response,
    )
    session = SimpleNamespace(session_id="test-session", context={}, get_context_for_llm=lambda *args, **kwargs: "")

    reply = AgentOrchestrator._generate_recovery_reply(
        dummy,
        session=session,
        user_input="liste os arquivos de imagens da minha pasta Downloads",
        reason="no_plan_resolved",
        last_tool_data=None,
        last_action_id="system.control.fs.list",
    )

    assert "guidance" in reply.lower()
    assert "execution confirmation" in reply.lower()
    assert session.context.get("last_recovery_sanitization", {}).get("reason_code") in {"guidance_only", "no_fresh_tool_evidence"}


def test_recovery_reply_without_tool_data_blocks_attachment_claim():
    dummy = SimpleNamespace(
        llm_manager=SimpleNamespace(generate_text=lambda *args, **kwargs: "Seguem os arquivos anexados à nossa conversa."),
        _session_locale=lambda _session: "pt-BR",
        _t=lambda _session, key, **kwargs: key,
        _looks_like_unverified_progress_claim=AgentOrchestrator._looks_like_unverified_progress_claim,
        _looks_like_success_claim=AgentOrchestrator._looks_like_success_claim,
        _looks_like_guidance_only_reply=AgentOrchestrator._looks_like_guidance_only_reply,
        _looks_like_attachment_claim=AgentOrchestrator._looks_like_attachment_claim,
        _sanitize_user_facing_response=AgentOrchestrator._sanitize_user_facing_response,
    )
    session = SimpleNamespace(session_id="test-session", context={}, get_context_for_llm=lambda *args, **kwargs: "")

    reply = AgentOrchestrator._generate_recovery_reply(
        dummy,
        session=session,
        user_input="anexe os arquivos",
        reason="no_plan_resolved",
        last_tool_data=None,
        last_action_id="shell.control.execute",
    )

    assert reply == ""
    assert session.context.get("last_recovery_sanitization", {}).get("reason_code") == "attachment_not_confirmed"


def test_sanitize_user_facing_response_requires_sent_confirmation_for_attachment_claims():
    audit = {}
    reply = AgentOrchestrator._sanitize_user_facing_response(
        "Seguem os arquivos anexados à nossa conversa.",
        language="pt-BR",
        has_fresh_tool_evidence=True,
        attachment_payload_present=False,
        attachment_delivery_state={
            "requested": ["/tmp/a.png"],
            "resolved": [{"path": "/tmp/a.png", "name": "a.png"}],
            "prepared": [{"path": "/tmp/a.png", "name": "a.png"}],
            "sent": [],
            "errors": [],
            "status": "prepared",
            "confirmed": False,
        },
        audit=audit,
    )

    assert reply == ""
    assert audit["reason_code"] == "attachment_not_confirmed"
    assert audit["evidence_required"] == "sent_attachments"


def test_sanitize_user_facing_response_blocks_execution_claim_without_fresh_evidence():
    audit = {}
    reply = AgentOrchestrator._sanitize_user_facing_response(
        "Concluído, verifiquei e atualizei o estado com sucesso.",
        language="pt-BR",
        has_fresh_tool_evidence=False,
        attachment_payload_present=False,
        audit=audit,
    )

    assert reply == ""
    assert audit["reason_code"] == "no_fresh_tool_evidence"
    assert audit["evidence_required"] == "fresh_action_observation"


def test_sanitize_user_facing_response_blocks_attachment_claim_without_payload():
    audit = {}
    reply = AgentOrchestrator._sanitize_user_facing_response(
        "Seguem os arquivos anexados à nossa conversa.",
        language="pt-BR",
        has_fresh_tool_evidence=True,
        attachment_payload_present=False,
        audit=audit,
    )

    assert reply == ""
    assert audit["reason_code"] == "attachment_not_confirmed"
    assert audit["evidence_required"] == "sent_attachments"


def test_sanitize_user_facing_response_allows_grounded_execution_and_attachment_claims_when_evidence_exists():
    audit = {}
    reply = AgentOrchestrator._sanitize_user_facing_response(
        "Concluído, anexei os arquivos e verifiquei o resultado com sucesso.",
        language="pt-BR",
        has_fresh_tool_evidence=True,
        attachment_payload_present=False,
        attachment_delivery_state={
            "requested": ["/tmp/a.png"],
            "resolved": [{"path": "/tmp/a.png", "name": "a.png"}],
            "prepared": [{"path": "/tmp/a.png", "name": "a.png"}],
            "sent": [{"path": "/tmp/a.png", "status": "sent"}],
            "errors": [],
            "status": "sent",
            "confirmed": True,
        },
        audit=audit,
    )

    lowered = reply.lower()
    assert "concluído" in lowered
    assert "anexei" in lowered
    assert "verifiquei" in lowered
    assert "sucesso" in lowered
    assert audit["reason_code"] is None
    assert audit["changed"] is False


def test_sanitize_user_facing_response_reports_attachment_timeout_reason_code():
    audit = {}
    reply = AgentOrchestrator._sanitize_user_facing_response(
        "Seguem os arquivos anexados à nossa conversa.",
        language="pt-BR",
        has_fresh_tool_evidence=True,
        attachment_payload_present=True,
        attachment_delivery_state={
            "requested": ["/tmp/a.png"],
            "resolved": [{"path": "/tmp/a.png", "name": "a.png"}],
            "prepared": [{"path": "/tmp/a.png", "name": "a.png"}],
            "sent": [],
            "errors": [{"path": "/tmp/a.png", "error": "Timed out"}],
            "status": "failed",
            "confirmed": False,
        },
        audit=audit,
    )

    assert reply == ""
    assert audit["reason_code"] == "attachment_delivery_failed"
    assert audit["evidence_required"] == "sent_attachments"


def test_sanitize_user_facing_response_reports_partial_attachment_reason_code():
    audit = {}
    reply = AgentOrchestrator._sanitize_user_facing_response(
        "Seguem os arquivos anexados à nossa conversa.",
        language="pt-BR",
        has_fresh_tool_evidence=True,
        attachment_payload_present=True,
        attachment_delivery_state={
            "requested": ["/tmp/a.png", "/tmp/b.png"],
            "resolved": [{"path": "/tmp/a.png", "name": "a.png"}, {"path": "/tmp/b.png", "name": "b.png"}],
            "prepared": [{"path": "/tmp/a.png", "name": "a.png"}, {"path": "/tmp/b.png", "name": "b.png"}],
            "sent": [{"path": "/tmp/a.png", "status": "sent"}],
            "errors": [{"path": "/tmp/b.png", "error": "Timed out"}],
            "status": "partial",
            "confirmed": False,
        },
        audit=audit,
    )

    assert reply == ""
    assert audit["reason_code"] == "attachment_delivery_partial"
    assert audit["evidence_required"] == "sent_attachments"
