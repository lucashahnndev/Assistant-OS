from pathlib import Path
from types import SimpleNamespace
import json

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
