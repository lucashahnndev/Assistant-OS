from pathlib import Path
from types import SimpleNamespace
import json

from core.session import Session
from core.session_event_pipeline import SessionEventPipeline


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
    pipeline.process_event(
        {
            "type": "weg_scene_reset",
            "session_id": "sess-4",
            "payload": {"scene": "reset"},
        }
    )

    events_lines = Path(pipeline.events_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(events_lines) == 5
    assert message_event["category"] == "message"
    assert stream_event["category"] == "stream"
    assert complete_event["category"] == "completion"
    assert worker_event["category"] == "worker"
    assert len(session.event_timeline) == 5

    messages_index = json.loads(Path(pipeline.indices_dir, "messages.index.json").read_text(encoding="utf-8"))
    turns_index = json.loads(Path(pipeline.indices_dir, "turns.index.json").read_text(encoding="utf-8"))
    streams_index = json.loads(Path(pipeline.indices_dir, "streams.index.json").read_text(encoding="utf-8"))
    workers_index = json.loads(Path(pipeline.indices_dir, "workers.index.json").read_text(encoding="utf-8"))

    assert messages_index["items"]["msg-1"]["message_id"] == "msg-1"
    assert messages_index["items"]["msg-1"]["role"] == "user"
    assert turns_index["items"]["4"]["user_message_id"] == "msg-1"
    assert turns_index["items"]["4"]["stream_ids"] == ["stream-1"]
    assert streams_index["items"]["stream-1"]["status"] == "completed"
    assert streams_index["items"]["stream-1"]["sequence_last"] == 2
    assert workers_index["items"]["work-1"]["status"] == "completed"

    messages_count = len(messages_index["items"])
    assert messages_count == 1


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
