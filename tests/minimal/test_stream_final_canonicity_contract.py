import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.orchestrator import AgentOrchestrator
from core.session import Session
from core.session_event_pipeline import SessionEventPipeline, build_session_snapshot


def _write_session_files(session: Session, base_data_dir: Path) -> Path:
    session_dir = base_data_dir / "sessions" / session.session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps(session.to_dict(), ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    (session_dir / "chat.json").write_text(
        json.dumps(session.history, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    return session_dir


@pytest.mark.parametrize(
    "case_name, diagnostics, use_sanitizer, add_tool_result",
    [
        (
            "provider_empty",
            {"last_provider_diagnostics": {"provider_parse_status": "empty_output", "provider_fallback_reason": "provider_parse_error"}},
            False,
            False,
        ),
        (
            "provider_invalid_json",
            {"last_provider_diagnostics": {"provider_parse_status": "invalid_json", "provider_fallback_reason": "provider_parse_error"}},
            False,
            False,
        ),
        (
            "provider_reply_without_text",
            {"last_provider_diagnostics": {"provider_parse_status": "invalid_reply_payload", "provider_fallback_reason": "provider_contract_error"}},
            False,
            False,
        ),
        (
            "resolver_low_confidence",
            {
                "last_confidence_diagnostics": {
                    "score": 0.12,
                    "threshold": 0.65,
                    "reason_codes": ["invalid_reply_payload"],
                    "reason_types": ["format"],
                    "semantic_authority": False,
                    "action": "reply",
                    "action_is_reply": True,
                    "model_used": "stub-model",
                },
                "last_confidence_rejection": {"error_code": "low_confidence"},
            },
            False,
            False,
        ),
        (
            "recovery_empty",
            {"last_recovery_sanitization": {"changed": True, "reason_code": "recovery_empty", "evidence_required": "final_response"}},
            False,
            False,
        ),
        (
            "sanitizer_blocked",
            {"last_recovery_sanitization": {"changed": True, "reason_code": "no_fresh_tool_evidence", "evidence_required": "fresh_action_observation"}},
            True,
            False,
        ),
        (
            "tool_result_synthesis_failed",
            {
                "last_provider_diagnostics": {"provider_parse_status": "ok", "provider_fallback_reason": None},
                "last_observation_status": "success",
                "last_observation_reason": "tool_result_available",
            },
            False,
            True,
        ),
    ],
)
def test_stream_complete_does_not_replace_canonical_assistant_final(
    tmp_path,
    monkeypatch,
    case_name,
    diagnostics,
    use_sanitizer,
    add_tool_result,
):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session = Session(session_id=f"sess-{case_name}", source="web")
    user_message = session.add_message("user", f"Pergunta de teste para {case_name}.")
    thought = session.add_thought(
        f"Rascunho interno para {case_name}.",
        work_id=f"work-{case_name}",
        source="reasoning",
    )

    session.context.update(diagnostics)
    session.state_summary.update(diagnostics)
    if add_tool_result:
        session.state_summary["last_observation_status"] = "success"
        session.state_summary["last_observation_reason"] = "tool_result_available"

    pipeline = SessionEventPipeline(session, base_data_dir=str(tmp_path))
    turn_id = user_message["turn_id"]
    stream_id = f"stream-{case_name}"
    work_id = f"work-{case_name}"

    assistant_chunk = pipeline.process_event(
        {
            "type": "assistant_chunk",
            "session_id": session.session_id,
            "turn_id": turn_id,
            "stream_id": stream_id,
            "sequence": 0,
            "payload": {"content": "processing"},
        }
    )
    worker_event = None
    if add_tool_result:
        worker_event = pipeline.process_event(
            {
                "type": "worker_state",
                "session_id": session.session_id,
                "turn_id": turn_id,
                "work_id": work_id,
                "payload": {
                    "status": "completed",
                    "label": "Tool result ready",
                    "summary": "tool result available",
                },
            }
        )

    complete_event = pipeline.process_event(
        {
            "type": "complete",
            "session_id": session.session_id,
            "turn_id": turn_id,
            "stream_id": stream_id,
            "sequence": 1,
            "target": "stream",
            "payload": {"content": "stream complete"},
        }
    )

    if use_sanitizer:
        audit = {}
        final_text = AgentOrchestrator._sanitize_user_facing_response(
            "",
            language="pt-BR",
            has_fresh_tool_evidence=bool(add_tool_result),
            attachment_payload_present=False,
            audit=audit,
        )
        session.context["last_recovery_sanitization"] = audit
        session.state_summary["last_recovery_sanitization"] = dict(audit)
    else:
        reason_code = "recovery_error" if add_tool_result else "recovery_empty"
        final_text = AgentOrchestrator._build_honest_fallback_reply(
            language="pt-BR",
            reason_code=reason_code,
            detail="synthesis failed" if add_tool_result else "",
        )

    assistant_message = session.add_message(
        "assistant",
        final_text,
        reply_to_message_id=user_message["id"],
        work_id=work_id,
    )

    session_dir = _write_session_files(session, Path(tmp_path))
    snapshot = build_session_snapshot(session.session_id, base_data_dir=str(tmp_path))

    chat_path = session_dir / "chat.json"
    events_path = session_dir / "events.jsonl"
    messages_index_path = session_dir / "messages.index.json"
    streams_index_path = session_dir / "streams.index.json"
    thoughts_index_path = session_dir / "thoughts.index.json"

    assert chat_path.exists()
    assert events_path.exists()
    assert messages_index_path.exists()
    assert streams_index_path.exists()
    assert thoughts_index_path.exists()

    chat = json.loads(chat_path.read_text(encoding="utf-8"))
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    messages_index = json.loads(messages_index_path.read_text(encoding="utf-8"))
    streams_index = json.loads(streams_index_path.read_text(encoding="utf-8"))
    thoughts_index = json.loads(thoughts_index_path.read_text(encoding="utf-8"))

    assert chat[-1]["role"] == "assistant"
    assert chat[-1]["content"] == final_text
    assert chat[-1]["content"].strip()
    assert all(msg.get("type") != "reasoning" for msg in chat)
    assert len(chat) == 2

    assert snapshot["chat"] == chat
    assert snapshot["indices"]["messages"]["items"][assistant_message["id"]]["role"] == "assistant"
    assert snapshot["indices"]["messages"]["items"][assistant_message["id"]]["content_preview"] == final_text[:120]
    assert snapshot["indices"]["streams"]["items"][stream_id]["status"] == "completed"
    assert snapshot["indices"]["streams"]["items"][stream_id]["is_active"] is False
    assert snapshot["indices"]["turns"]["items"][str(turn_id)]["status"] == "completed"
    assert snapshot["indices"]["turns"]["items"][str(turn_id)]["assistant_message_ids"][-1] == assistant_message["id"]

    assert messages_index["items"][user_message["id"]]["role"] == "user"
    assert messages_index["items"][assistant_message["id"]]["role"] == "assistant"
    assert messages_index["items"][assistant_message["id"]]["turn_id"] == turn_id
    assert messages_index["items"][assistant_message["id"]]["content_preview"] == final_text[:120]
    assert streams_index["items"][stream_id]["turn_id"] == turn_id
    assert streams_index["items"][stream_id]["status"] == "completed"
    assert streams_index["items"][stream_id]["sequence_last"] == 1

    assert thoughts_index["items"][thought["id"]]["thought_id"] == thought["id"]
    assert thoughts_index["items"][thought["id"]]["message_id"] == assistant_message["id"]
    assert thought["thought"] not in {msg["content"] for msg in chat}
    assert thought["thought"] not in messages_index["items"][assistant_message["id"]]["content_preview"]

    assert any(event.get("type") == "assistant_chunk" and event.get("turn_id") == turn_id for event in events)
    assert any(event.get("type") == "complete" and event.get("target") == "stream" and event.get("stream_id") == stream_id for event in events)
    assert any(event.get("type") == "message_added" and event.get("role") == "assistant" and event.get("turn_id") == turn_id for event in events)
    assert all(event.get("turn_id") == turn_id for event in events if event.get("type") in {"message_added", "assistant_chunk", "complete", "worker_state", "reasoning_chunk"})

    if "last_provider_diagnostics" in diagnostics:
        assert session.state_summary["last_provider_diagnostics"] == diagnostics["last_provider_diagnostics"]
    if "last_confidence_diagnostics" in diagnostics:
        assert session.state_summary["last_confidence_diagnostics"]["semantic_authority"] is False
    if "last_recovery_sanitization" in diagnostics:
        assert session.context["last_recovery_sanitization"]["reason_code"] == diagnostics["last_recovery_sanitization"]["reason_code"]
    if add_tool_result:
        assert worker_event is not None
        assert snapshot["indices"]["workers"]["items"][work_id]["status"] == "completed"
        assert snapshot["indices"]["workers"]["items"][work_id]["work_id"] == work_id

    assert complete_event["target"] == "stream"
    assert complete_event["stream_id"] == stream_id
    assert complete_event["turn_id"] == turn_id
    assert assistant_message["content"].strip()
