import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.session import Session
from drivers.llm.base import ILLMProvider


def test_session_context_preserves_roles_and_metadata():
    session = Session(session_id="role-contract")
    session.history = [
        {
            "id": "msg-system",
            "role": "system",
            "content": "policy note",
            "type": "reasoning",
            "turn_id": 2,
        },
        {
            "id": "msg-tool",
            "role": "tool",
            "content": "tool observation",
            "type": "observation",
            "turn_id": 2,
        },
        {
            "id": "msg-recovery",
            "role": "recovery",
            "content": "recovery diagnostic",
            "type": "diagnostic",
            "turn_id": 2,
        },
        {
            "id": "msg-legacy-diagnostic",
            "kind": "diagnostic",
            "content": "legacy diagnostic without explicit role",
            "turn_id": 2,
        },
        {
            "id": "msg-user",
            "role": "user",
            "content": "real user speech",
            "turn_id": 3,
        },
    ]

    context = session.get_context_for_llm(limit_tokens=4000, limit_msgs=10)

    assert any(msg["role"] == "system" and msg["content"] == "policy note" for msg in context)
    assert any(msg["role"] == "tool" and msg["content"] == "tool observation" for msg in context)
    assert any(msg["role"] == "recovery" and msg["content"] == "recovery diagnostic" for msg in context)
    assert any(msg["role"] == "diagnostic" or msg["role"] == "context" for msg in context if msg["content"] == "legacy diagnostic without explicit role")
    assert any(msg["role"] == "user" and msg["content"] == "real user speech" for msg in context)
    assert all(msg["role"] != "user" or msg["metadata"].get("origin_role") == "user" for msg in context)
    assert all("origin" in msg and "kind" in msg and "metadata" in msg for msg in context)
    assert all(msg["metadata"].get("origin_role") != "system" or msg["role"] == "system" for msg in context)


def test_chat_messages_preserve_technical_context_out_of_user_role():
    history = [
        {
            "role": "system",
            "content": "policy note",
            "origin": "session",
            "kind": "policy",
            "message_id": "msg-system",
            "turn_id": 2,
        },
        {
            "role": "diagnostic",
            "content": "provider diagnostics",
            "origin": "session",
            "kind": "diagnostic",
            "message_id": "msg-diagnostic",
            "turn_id": 3,
        },
        {
            "role": "tool",
            "content": "tool output",
            "tool_call_id": "call-1",
            "origin": "tool",
            "kind": "evidence",
            "message_id": "msg-tool",
            "turn_id": 3,
        },
        {
            "role": "assistant",
            "content": "assistant reply",
            "origin": "session",
            "kind": "assistant",
            "message_id": "msg-assistant",
            "turn_id": 4,
        },
        {
            "role": "user",
            "content": "prior user speech",
            "origin": "user",
            "kind": "user",
            "message_id": "msg-user",
            "turn_id": 5,
        },
    ]

    messages = ILLMProvider.build_chat_messages(
        history=history,
        user_input="current user speech",
        system_prompt="base system prompt",
        allow_tool_role=True,
    )

    assert messages[0] == {"role": "system", "content": "base system prompt"}
    assert any(msg["role"] == "system" and msg["content"] == "policy note" for msg in messages)
    assert any(msg["role"] == "system" and "[TECHNICAL CONTEXT - NOT USER SPEECH]" in msg["content"] for msg in messages)
    assert any(msg["role"] == "tool" and msg.get("tool_call_id") == "call-1" for msg in messages)
    assert any(msg["role"] == "assistant" and msg["content"] == "assistant reply" for msg in messages)
    assert messages[-1] == {"role": "user", "content": "current user speech"}
    assert all(msg["role"] != "user" or msg["content"] == "current user speech" or msg["content"] == "prior user speech" for msg in messages)


def test_gemini_payload_keeps_technical_context_in_system_instruction():
    history = [
        {"role": "system", "content": "policy note", "origin": "session", "kind": "policy"},
        {"role": "diagnostic", "content": "provider diagnostics", "origin": "session", "kind": "diagnostic"},
        {"role": "assistant", "content": "assistant reply", "origin": "session", "kind": "assistant"},
        {"role": "user", "content": "prior user speech", "origin": "user", "kind": "user"},
    ]

    system_instruction, contents = ILLMProvider.build_gemini_payload(
        history=history,
        user_input="current user speech",
        system_prompt="base system prompt",
    )

    assert "base system prompt" in system_instruction
    assert "policy note" in system_instruction
    assert "provider diagnostics" in system_instruction
    assert "[TECHNICAL CONTEXT - NOT USER SPEECH]" in system_instruction
    assert all(item["role"] in {"user", "model"} for item in contents)
    assert any(item["role"] == "model" and item["parts"][0]["text"] == "assistant reply" for item in contents)
    assert contents[-1]["role"] == "user"
    assert contents[-1]["parts"][0]["text"] == "current user speech"
