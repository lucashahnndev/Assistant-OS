from pathlib import Path
from types import SimpleNamespace
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.orchestrator import AgentOrchestrator
from core.session import Session
from core.session_event_pipeline import (
    SessionEventPipeline,
    build_session_snapshot,
    filter_conversational_chat_history,
)
from server.auth import get_current_user
from server.routes import sessions as sessions_routes


class _OrchestratorStub:
    def __init__(self, session):
        self._session = session

    def get_session_robust(self, session_id):
        if session_id == self._session.session_id:
            return self._session
        return None

    def get_runtime_metrics(self, session_id):
        return {"session_id": session_id, "healthy": True}


def _build_client(session, base_data_dir: Path):
    app = FastAPI()
    app.state.kernel = SimpleNamespace(
        orchestrator=_OrchestratorStub(session),
        config_manager=SimpleNamespace(base_data_dir=str(base_data_dir)),
    )
    app.include_router(sessions_routes.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="admin", username="tester")
    return TestClient(app)


def test_session_event_pipeline_normalizes_and_persists_events(tmp_path):
    session = SimpleNamespace(session_id="sess-1")
    pipeline = SessionEventPipeline(session, base_data_dir=str(tmp_path))

    raw = {
        "type": "message_added",
        "session_id": "sess-1",
        "payload": {
            "message_id": "msg-1",
            "reply_to_message_id": "user-1",
            "content": "hello",
        },
        "turn_id": 4,
        "work_id": "work-1",
        "channel": "websocket",
        "interface": "web",
        "source": "server_driver",
    }
    normalized = pipeline.normalize_event(raw)

    assert normalized["event_id"]
    assert normalized["type"] == "message_added"
    assert normalized["event_type"] == "message_added"
    assert normalized["category"] == "message"
    assert normalized["message_id"] == "msg-1"
    assert normalized["reply_to_message_id"] == "user-1"
    assert normalized["turn_id"] == 4
    assert normalized["work_id"] == "work-1"
    assert normalized["channel"] == "websocket"
    assert normalized["interface"] == "web"
    assert normalized["source"] == "server_driver"
    assert normalized["payload"]["content"] == "hello"
    assert normalized["raw"]["type"] == "message_added"

    persisted = pipeline.append_event(raw)
    assert persisted["event_id"]
    assert Path(pipeline.events_path).exists()

    lines = Path(pipeline.events_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    stored = json.loads(lines[0])
    assert stored["event_id"] == persisted["event_id"]
    assert stored["category"] == "message"
    assert stored["payload"]["content"] == "hello"


def test_session_event_pipeline_classifies_core_categories(tmp_path):
    session = SimpleNamespace(session_id="sess-2")
    pipeline = SessionEventPipeline(session, base_data_dir=str(tmp_path))

    cases = [
        ("assistant_chunk", "stream"),
        ("complete", "completion"),
        ("visual.wegena.scene_reset", "visual"),
        ("weg_scene_reset", "visual"),
        ("worker_state", "worker"),
        ("session_updated", "session"),
        ("status", "status"),
    ]

    for event_type, expected_category in cases:
        event = pipeline.normalize_event({
            "type": event_type,
            "session_id": "sess-2",
            "target": "stream" if event_type == "complete" else None,
            "payload": {"content": "ok"},
        })
        assert event["event_type"] == event_type
        assert event["type"] == event_type
        assert event["category"] == expected_category


def test_session_event_pipeline_preserves_event_type_to_type_compatibility(tmp_path):
    session = SimpleNamespace(session_id="sess-3")
    pipeline = SessionEventPipeline(session, base_data_dir=str(tmp_path))

    event = pipeline.normalize_event({
        "event_type": "assistant_response",
        "session_id": "sess-3",
        "payload": {"content": "hi"},
    })

    assert event["event_type"] == "assistant_response"
    assert event["type"] == "assistant_response"
    assert event["category"] == "completion"


def test_session_event_pipeline_updates_indices(tmp_path):
    session = SimpleNamespace(session_id="sess-4", event_timeline=[])
    pipeline = SessionEventPipeline(session, base_data_dir=str(tmp_path))

    message_event = pipeline.process_event(
        {
            "type": "message_added",
            "session_id": "sess-4",
            "turn_id": 4,
            "payload": {
                "message_id": "msg-1",
                "id": "msg-1",
                "role": "user",
                "content": "hello there",
            },
        }
    )
    stream_event = pipeline.process_event(
        {
            "type": "assistant_chunk",
            "session_id": "sess-4",
            "turn_id": 4,
            "stream_id": "stream-1",
            "sequence": 1,
            "payload": {
                "content": "part one",
            },
        }
    )
    complete_event = pipeline.process_event(
        {
            "type": "complete",
            "session_id": "sess-4",
            "turn_id": 4,
            "stream_id": "stream-1",
            "sequence": 2,
            "target": "stream",
            "payload": {
                "content": "done",
            },
        }
    )
    worker_event = pipeline.process_event(
        {
            "type": "worker_state",
            "session_id": "sess-4",
            "turn_id": 4,
            "work_id": "work-1",
            "payload": {
                "status": "completed",
                "label": "Task finished",
                "last_thought": "all done",
            },
        }
    )
    reasoning_event = pipeline.process_event(
        {
            "type": "reasoning_chunk",
            "session_id": "sess-4",
            "turn_id": 4,
            "work_id": "work-1",
            "payload": {
                "thought_id": "thought-1",
                "visibility": "public",
                "kind": "reasoning",
                "content": "reasoning text",
                "summary": "reasoning summary",
            },
        }
    )
    media_event = pipeline.process_event(
        {
            "type": "media.added",
            "session_id": "sess-4",
            "turn_id": 4,
            "message_id": "msg-1",
            "work_id": "work-1",
            "payload": {
                "media_id": "media-1",
                "kind": "voice",
                "mime": "audio/webm",
                "path": "/tmp/media-1.webm",
                "size": 1234,
                "derived_refs": ["artifact-1"],
            },
        }
    )
    artifact_event = pipeline.process_event(
        {
            "type": "artifact.created",
            "session_id": "sess-4",
            "turn_id": 4,
            "message_id": "msg-1",
            "work_id": "work-1",
            "payload": {
                "artifact_id": "artifact-1",
                "artifact_type": "transcript",
                "path": "/tmp/artifact-1.txt",
                "summary": "artifact summary",
                "status": "ready",
            },
        }
    )
    card_event = pipeline.process_event(
        {
            "type": "card.created",
            "session_id": "sess-4",
            "turn_id": 4,
            "message_id": "msg-1",
            "work_id": "work-1",
            "payload": {
                "card_id": "card-1",
                "card_type": "summary",
                "payload": {"title": "Card"},
                "pinned": True,
                "ttl": 300,
            },
        }
    )
    wege_event = pipeline.process_event(
        {
            "type": "visual.wegena.scene_reset",
            "session_id": "sess-4",
            "turn_id": 4,
            "payload": {
                "scene_id": "scene-1",
                "scene_type": "reset",
                "composition_ref": "composition-1",
                "snapshot_ref": "snapshot-1",
                "status": "ok",
            },
        }
    )
    pipeline.process_event(
        {
            "type": "weg_scene_reset",
            "session_id": "sess-4",
            "payload": {"scene": "reset"},
        }
    )

    events_lines = Path(pipeline.events_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(events_lines) == 10
    assert message_event["category"] == "message"
    assert stream_event["category"] == "stream"
    assert complete_event["category"] == "completion"
    assert worker_event["category"] == "worker"
    assert reasoning_event["category"] == "reasoning"
    assert media_event["category"] == "media"
    assert artifact_event["category"] == "artifact"
    assert card_event["category"] == "card"
    assert wege_event["category"] == "visual"
    assert len(session.event_timeline) == 10

    messages_index = json.loads(Path(pipeline.indices_dir, "messages.index.json").read_text(encoding="utf-8"))
    turns_index = json.loads(Path(pipeline.indices_dir, "turns.index.json").read_text(encoding="utf-8"))
    streams_index = json.loads(Path(pipeline.indices_dir, "streams.index.json").read_text(encoding="utf-8"))
    workers_index = json.loads(Path(pipeline.indices_dir, "workers.index.json").read_text(encoding="utf-8"))
    thoughts_index = json.loads(Path(pipeline.indices_dir, "thoughts.index.json").read_text(encoding="utf-8"))
    media_index = json.loads(Path(pipeline.indices_dir, "media.index.json").read_text(encoding="utf-8"))
    artifacts_index = json.loads(Path(pipeline.indices_dir, "artifacts.index.json").read_text(encoding="utf-8"))
    cards_index = json.loads(Path(pipeline.indices_dir, "cards.index.json").read_text(encoding="utf-8"))
    wege_index = json.loads(Path(pipeline.indices_dir, "wegena.index.json").read_text(encoding="utf-8"))

    assert messages_index["items"]["msg-1"]["message_id"] == "msg-1"
    assert messages_index["items"]["msg-1"]["role"] == "user"
    assert turns_index["items"]["4"]["user_message_id"] == "msg-1"
    assert turns_index["items"]["4"]["stream_ids"] == ["stream-1"]
    assert streams_index["items"]["stream-1"]["status"] == "completed"
    assert streams_index["items"]["stream-1"]["sequence_last"] == 2
    assert workers_index["items"]["work-1"]["status"] == "completed"
    assert thoughts_index["items"]["thought-1"]["thought_id"] == "thought-1"
    assert media_index["items"]["media-1"]["media_id"] == "media-1"
    assert artifacts_index["items"]["artifact-1"]["artifact_id"] == "artifact-1"
    assert cards_index["items"]["card-1"]["card_id"] == "card-1"
    assert wege_index["items"]["scene-1"]["scene_id"] == "scene-1"
    assert "media-1" not in messages_index["items"]
    assert "artifact-1" not in messages_index["items"]
    assert "card-1" not in messages_index["items"]

    messages_count = len(messages_index["items"])
    assert messages_count == 1

    snapshot = build_session_snapshot("sess-4", base_data_dir=str(tmp_path), recent_events_limit=3)
    assert snapshot["session_id"] == "sess-4"
    assert snapshot["indices"]["messages"]["items"]["msg-1"]["message_id"] == "msg-1"
    assert snapshot["indices"]["thoughts"]["items"]["thought-1"]["thought_id"] == "thought-1"
    assert len(snapshot["events"]) == 3
    assert snapshot["events"][-1]["type"] == "weg_scene_reset"


def test_session_snapshot_builder_handles_missing_indexes(tmp_path):
    session_dir = Path(tmp_path, "sessions", "sess-empty")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(json.dumps({"session_id": "sess-empty"}), encoding="utf-8")
    (session_dir / "chat.json").write_text(json.dumps([]), encoding="utf-8")
    (session_dir / "events.jsonl").write_text("", encoding="utf-8")

    snapshot = build_session_snapshot("sess-empty", base_data_dir=str(tmp_path))
    assert snapshot["session_id"] == "sess-empty"
    assert snapshot["session"]["session_id"] == "sess-empty"
    assert snapshot["chat"] == []
    assert snapshot["events"] == []
    assert snapshot["indices"]["messages"]["items"] == {}
    assert snapshot["indices"]["wegena"]["items"] == {}


def test_session_snapshot_filters_reasoning_from_chat(tmp_path):
    session_dir = Path(tmp_path, "sessions", "sess-filtered")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(json.dumps({
        "session_id": "sess-filtered",
        "history": [
            {"role": "user", "type": "default", "content": "hello"},
            {"role": "system", "type": "reasoning", "content": "internal thought"},
            {"role": "assistant", "type": "default", "content": "hi there"},
        ],
    }), encoding="utf-8")
    (session_dir / "chat.json").write_text(json.dumps([
        {"role": "user", "type": "default", "content": "hello"},
        {"role": "system", "type": "reasoning", "content": "internal thought"},
        {"role": "assistant", "type": "default", "content": "hi there"},
    ]), encoding="utf-8")
    (session_dir / "events.jsonl").write_text("", encoding="utf-8")

    snapshot = build_session_snapshot("sess-filtered", base_data_dir=str(tmp_path))
    assert [msg["role"] for msg in snapshot["chat"]] == ["user", "assistant"]
    assert all(msg.get("type") != "reasoning" for msg in snapshot["chat"])


def test_session_add_message_routes_through_session_event_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session = Session(session_id="sess-live")
    msg = session.add_message("user", "hello pipeline")

    events_path = Path(tmp_path, "sessions", "sess-live", "events.jsonl")
    assert events_path.exists()
    event = json.loads(events_path.read_text(encoding="utf-8").strip().splitlines()[0])
    assert event["type"] == "message_added"
    assert event["event_type"] == "message_added"
    assert event["category"] == "message"
    assert event["message_id"] == msg["id"]
    assert event["payload"]["message_id"] == msg["id"]
    assert event["message"]["id"] == msg["id"]
    assert event["role"] == "user"

    messages_index = json.loads(Path(tmp_path, "sessions", "sess-live", "messages.index.json").read_text(encoding="utf-8"))
    assert messages_index["items"][msg["id"]]["message_id"] == msg["id"]


def test_reasoning_messages_are_routed_to_thoughts_and_filtered_from_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session = Session(session_id="sess-thoughts")
    msg = session.add_message(
        "system",
        "The user initiated a greeting. I will respond politely and keep it brief.",
        msg_type="reasoning",
        work_id="work-thoughts",
    )

    assert session.history == []
    assert len(session.thoughts) == 1
    assert msg.get("thought_id")

    events_path = Path(tmp_path, "sessions", "sess-thoughts", "events.jsonl")
    assert events_path.exists()
    stored_event = json.loads(events_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert stored_event["category"] == "reasoning"
    assert stored_event["type"] == "reasoning_chunk"
    assert stored_event["thought_id"] == msg["thought_id"]

    messages_index_path = Path(tmp_path, "sessions", "sess-thoughts", "messages.index.json")
    thoughts_index = json.loads(Path(tmp_path, "sessions", "sess-thoughts", "thoughts.index.json").read_text(encoding="utf-8"))

    assert not messages_index_path.exists()
    assert msg["thought_id"] in thoughts_index["items"]
    assert thoughts_index["items"][msg["thought_id"]]["content"] == msg["content"]
    assert thoughts_index["items"][msg["thought_id"]]["message_id"] == msg["id"]

    filtered = filter_conversational_chat_history([
        {"role": "user", "type": "default", "content": "hi"},
        {"role": "system", "type": "reasoning", "content": "internal"},
        {"role": "assistant", "type": "default", "content": "hello"},
    ])
    assert [entry["role"] for entry in filtered] == ["user", "assistant"]


def test_short_reply_thoughts_are_indexed_and_backlinked_to_assistant_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session = Session(session_id="sess-reply-thought")
    user_msg = session.add_message("user", "Please answer briefly.")

    thought = session.add_thought(
        "Preparing final response.",
        work_id="work-reply",
        source="reasoning",
    )
    assistant_msg = session.add_message(
        "assistant",
        "Absolutely. Here is the brief answer.",
        work_id="work-reply",
        reply_to_message_id=user_msg["id"],
    )

    thoughts_index = json.loads(Path(tmp_path, "sessions", "sess-reply-thought", "thoughts.index.json").read_text(encoding="utf-8"))
    thought_record = thoughts_index["items"][thought["id"]]

    assert user_msg["turn_id"] == assistant_msg["turn_id"]
    assert thought_record["turn_id"] == assistant_msg["turn_id"]
    assert thought_record["message_id"] == assistant_msg["id"]
    assert thought_record["work_id"] == "work-reply"
    assert thought_record["kind"] == "reasoning"
    assert thought_record["thinking_started_at"] is not None
    assert thought_record["thinking_duration_ms"] is not None
    assert thought_record["thinking_completed_at"] is not None
    assert thought_record["is_active"] is False

    events = Path(tmp_path, "sessions", "sess-reply-thought", "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert any(json.loads(line)["type"] == "reasoning_chunk" for line in events)
    assert any(json.loads(line)["type"] == "message_added" and json.loads(line)["role"] == "assistant" for line in events)


def test_session_thought_duration_fields_are_derived(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session_id = "sess-duration"
    session = SimpleNamespace(session_id=session_id, event_timeline=[], context={"current_turn_id": 7}, scratchpad={})
    pipeline = SessionEventPipeline(session, base_data_dir=str(tmp_path))

    turn_id = 7
    user_message = pipeline.process_event(
        {
            "type": "message_added",
            "session_id": session_id,
            "turn_id": turn_id,
            "timestamp": "2026-06-02T10:00:00Z",
            "payload": {
                "message_id": "user-duration",
                "role": "user",
                "content": "hello duration",
            },
        }
    )
    reasoning_event = pipeline.process_event(
        {
            "type": "reasoning_chunk",
            "session_id": session_id,
            "turn_id": turn_id,
            "timestamp": "2026-06-02T10:00:01Z",
            "work_id": "work-duration",
            "payload": {
                "thought_id": "thought-duration",
                "kind": "reasoning",
                "content": "thinking trace",
                "summary": "Thinking...",
            },
        }
    )
    stream_event = pipeline.process_event(
        {
            "type": "assistant_chunk",
            "session_id": session_id,
            "turn_id": turn_id,
            "stream_id": "stream-duration",
            "sequence": 1,
            "timestamp": "2026-06-02T10:00:01.500000Z",
            "payload": {"content": "stream part 1"},
        }
    )
    final_chunk = pipeline.process_event(
        {
            "type": "final_message_chunk",
            "session_id": session_id,
            "turn_id": turn_id,
            "stream_id": "stream-duration",
            "sequence": 2,
            "message_id": "assistant-duration",
            "timestamp": "2026-06-02T10:00:02.000000Z",
            "payload": {"content": "stream final chunk"},
        }
    )
    assistant_message = pipeline.process_event(
        {
            "type": "message_added",
            "session_id": session_id,
            "turn_id": turn_id,
            "timestamp": "2026-06-02T10:00:02.500000Z",
            "payload": {
                "message_id": "assistant-duration",
                "role": "assistant",
                "reply_to_message_id": "user-duration",
                "content": "final answer",
                "work_id": "work-duration",
            },
        }
    )
    complete_event = pipeline.process_event(
        {
            "type": "complete",
            "session_id": session_id,
            "turn_id": turn_id,
            "stream_id": "stream-duration",
            "timestamp": "2026-06-02T10:00:03.000000Z",
            "target": "stream",
            "payload": {"content": "stream complete"},
        }
    )

    session_dir = Path(tmp_path, "sessions", session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"session_id": session_id, "context": {"current_turn_id": turn_id}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (session_dir / "chat.json").write_text(
        json.dumps([
            {"role": "user", "type": "default", "content": "hello duration"},
            {"role": "assistant", "type": "default", "content": "final answer"},
        ], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    client = _build_client(session, Path(tmp_path))
    response = client.get(f"/api/sessions/{session_id}/snapshot")
    assert response.status_code == 200
    route_snapshot = response.json()

    turns_index = json.loads((session_dir / "turns.index.json").read_text(encoding="utf-8"))
    streams_index = json.loads((session_dir / "streams.index.json").read_text(encoding="utf-8"))
    thoughts_index = json.loads((session_dir / "thoughts.index.json").read_text(encoding="utf-8"))
    snapshot = build_session_snapshot(session_id, base_data_dir=str(tmp_path))

    turn_record = turns_index["items"][str(turn_id)]
    stream_record = streams_index["items"]["stream-duration"]
    thought_record = thoughts_index["items"]["thought-duration"]

    assert turn_record["thinking_started_at"] == "2026-06-02T10:00:00Z"
    assert turn_record["thinking_completed_at"] == "2026-06-02T10:00:03.000000Z"
    assert turn_record["thinking_duration_ms"] == 3000
    assert turn_record["turn_duration_ms"] == 3000
    assert turn_record["is_active"] is False

    assert stream_record["thinking_started_at"] == "2026-06-02T10:00:00Z"
    assert stream_record["thinking_completed_at"] == "2026-06-02T10:00:03.000000Z"
    assert stream_record["stream_duration_ms"] == 1500
    assert stream_record["thinking_duration_ms"] == 3000
    assert stream_record["is_active"] is False

    assert thought_record["thinking_started_at"] == "2026-06-02T10:00:00Z"
    assert thought_record["thinking_completed_at"] == "2026-06-02T10:00:03.000000Z"
    assert thought_record["thinking_duration_ms"] == 3000
    assert thought_record["turn_duration_ms"] == 3000
    assert thought_record["stream_duration_ms"] == 1500
    assert thought_record["is_active"] is False

    assert user_message["turn_id"] == turn_id
    assert assistant_message["turn_id"] == turn_id
    assert reasoning_event["turn_id"] == turn_id
    assert stream_event["turn_id"] == turn_id
    assert final_chunk["turn_id"] == turn_id
    assert complete_event["turn_id"] == turn_id

    assert snapshot["indices"]["turns"]["items"][str(turn_id)]["thinking_duration_ms"] == 3000
    assert snapshot["indices"]["streams"]["items"]["stream-duration"]["stream_duration_ms"] == 1500
    assert snapshot["indices"]["thoughts"]["items"]["thought-duration"]["thinking_duration_ms"] == 3000
    assert route_snapshot["indices"]["turns"]["items"][str(turn_id)]["thinking_duration_ms"] == 3000
    assert route_snapshot["indices"]["streams"]["items"]["stream-duration"]["stream_duration_ms"] == 1500
    assert route_snapshot["indices"]["thoughts"]["items"]["thought-duration"]["thinking_duration_ms"] == 3000


def test_reply_reasoning_falls_back_to_proactive_chunk_when_missing():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._build_proactive_reasoning_chunk = lambda session, plan: "Preparing final response."

    session = SimpleNamespace(session_id="sess-reply-fallback", context={})
    plan = SimpleNamespace(action_id="reply", thought="")

    assert AgentOrchestrator._resolve_reply_reasoning(orchestrator, session, plan) == "Preparing final response."
