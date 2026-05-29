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
    )
    session = SimpleNamespace(session_id="test-session", get_context_for_llm=lambda *args, **kwargs: "")

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
    assert "ainda não consegui confirmar" in reply.lower()


def test_recovery_reply_without_tool_data_does_not_claim_completion():
    dummy = SimpleNamespace(
        llm_manager=SimpleNamespace(
            generate_text=lambda *args, **kwargs: "I've created the `teste.txt` file with \"123\" inside for you, and it's now saved in your Videos folder."
        ),
        _session_locale=lambda _session: "en",
        _t=lambda _session, key, **kwargs: key,
        _looks_like_unverified_progress_claim=AgentOrchestrator._looks_like_unverified_progress_claim,
        _looks_like_success_claim=AgentOrchestrator._looks_like_success_claim,
    )
    session = SimpleNamespace(session_id="test-session", get_context_for_llm=lambda *args, **kwargs: "")

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
    assert "i can't confirm" in reply.lower() or "i cannot confirm" in reply.lower()
