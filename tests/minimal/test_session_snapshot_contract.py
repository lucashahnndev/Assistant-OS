import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.session import Session
from core.session_event_pipeline import SessionEventPipeline, build_session_snapshot
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


def _write_session_files(session: Session, base_data_dir: Path) -> None:
    session_dir = base_data_dir / "sessions" / session.session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(json.dumps(session.to_dict(), ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    (session_dir / "chat.json").write_text(json.dumps(session.history, ensure_ascii=False, default=str, indent=2), encoding="utf-8")


def test_snapshot_contract_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session_id = "snapshot-smoke"
    session = Session(session_id=session_id, source="web")

    user_message = session.add_message("user", "Hello snapshot contract")
    assistant_message = session.add_message(
        "assistant",
        "Snapshot contract acknowledged.",
        reply_to_message_id=user_message["id"],
        work_id="work-smoke",
    )

    pipeline = SessionEventPipeline(session, base_data_dir=str(tmp_path))
    stream_id = "stream-smoke"
    work_id = "work-smoke"
    turn_id = session.context["current_turn_id"]

    pipeline.process_event(
        {
            "type": "assistant_chunk",
            "session_id": session_id,
            "turn_id": turn_id,
            "stream_id": stream_id,
            "sequence": 1,
            "payload": {"content": "stream part 1"},
        }
    )
    pipeline.process_event(
        {
            "type": "final_message_chunk",
            "session_id": session_id,
            "turn_id": turn_id,
            "stream_id": stream_id,
            "sequence": 2,
            "message_id": assistant_message["id"],
            "payload": {"content": "stream final chunk"},
        }
    )
    complete_stream = pipeline.process_event(
        {
            "type": "complete",
            "session_id": session_id,
            "turn_id": turn_id,
            "stream_id": stream_id,
            "sequence": 3,
            "target": "stream",
            "payload": {"content": "stream complete"},
        }
    )
    status_event = pipeline.process_event(
        {
            "type": "status",
            "session_id": session_id,
            "turn_id": turn_id,
            "payload": {"phase": "working", "message": "streaming"},
        }
    )
    reasoning_event = pipeline.process_event(
        {
            "type": "reasoning_chunk",
            "session_id": session_id,
            "turn_id": turn_id,
            "work_id": work_id,
            "payload": {
                "thought_id": "thought-smoke",
                "kind": "reasoning",
                "content": "reasoning trace",
                "summary": "reasoning summary",
            },
        }
    )
    media_event = pipeline.process_event(
        {
            "type": "media.added",
            "session_id": session_id,
            "turn_id": turn_id,
            "message_id": assistant_message["id"],
            "work_id": work_id,
            "payload": {
                "media_id": "media-smoke",
                "kind": "voice",
                "mime": "audio/webm",
                "path": "/tmp/media-smoke.webm",
                "derived_refs": ["artifact-smoke"],
            },
        }
    )
    artifact_event = pipeline.process_event(
        {
            "type": "artifact.created",
            "session_id": session_id,
            "turn_id": turn_id,
            "message_id": assistant_message["id"],
            "work_id": work_id,
            "payload": {
                "artifact_id": "artifact-smoke",
                "artifact_type": "transcript",
                "path": "/tmp/artifact-smoke.txt",
                "summary": "artifact summary",
                "status": "ready",
            },
        }
    )
    card_event = pipeline.process_event(
        {
            "type": "card.created",
            "session_id": session_id,
            "turn_id": turn_id,
            "message_id": assistant_message["id"],
            "work_id": work_id,
            "payload": {
                "card_id": "card-smoke",
                "card_type": "summary",
                "payload": {"title": "Card smoke"},
                "pinned": True,
                "ttl": 300,
            },
        }
    )
    wege_event = pipeline.process_event(
        {
            "type": "visual.wegena.scene_reset",
            "session_id": session_id,
            "turn_id": turn_id,
            "payload": {
                "scene_id": "scene-smoke",
                "scene_type": "reset",
                "composition_ref": "composition-smoke",
                "snapshot_ref": "snapshot-smoke",
                "status": "ok",
            },
        }
    )
    complete_legacy = pipeline.process_event(
        {
            "type": "complete",
            "session_id": session_id,
            "turn_id": turn_id,
            "target": "legacy",
            "payload": {"content": "legacy complete"},
        }
    )

    _write_session_files(session, Path(tmp_path))

    client = _build_client(session, Path(tmp_path))
    response = client.get(f"/api/sessions/{session_id}/snapshot")
    assert response.status_code == 200
    snapshot = response.json()

    direct_snapshot = build_session_snapshot(session_id, base_data_dir=str(tmp_path))
    assert direct_snapshot["session_id"] == session_id
    assert direct_snapshot["chat"] == session.history

    assert snapshot["session_id"] == session_id
    assert snapshot["session"]["session_id"] == session_id
    assert snapshot["chat"] == session.history
    assert snapshot["current"]["turn_id"] == turn_id
    assert snapshot["current"]["current_turn_id"] == turn_id
    assert snapshot["current"]["legacy_turn_id"] == session.turn_id
    assert len(snapshot["events"]) == 12
    assert snapshot["events"][-1]["target"] == "legacy"
    stream_complete_event = next(event for event in snapshot["events"] if event.get("type") == "complete" and event.get("target") == "stream")
    legacy_complete_event = next(event for event in snapshot["events"] if event.get("type") == "complete" and event.get("target") == "legacy")
    assert stream_complete_event["stream_id"] == stream_id
    assert stream_complete_event["type"] == "complete"
    assert stream_complete_event["event_type"] == "complete"
    assert snapshot["events"][-1]["type"] == "complete"
    assert snapshot["events"][-1]["event_type"] == "complete"
    assert snapshot["events"][-1]["target"] == "legacy"
    assert snapshot["events"][-1]["category"] == "legacy"
    assert legacy_complete_event["target"] == "legacy"
    assert legacy_complete_event["category"] == "legacy"

    assert snapshot["indices"]["messages"]["items"][user_message["id"]]["message_id"] == user_message["id"]
    assert snapshot["indices"]["messages"]["items"][assistant_message["id"]]["message_id"] == assistant_message["id"]
    assert len(snapshot["indices"]["messages"]["items"]) == 2
    assert "media-smoke" not in snapshot["indices"]["messages"]["items"]
    assert "artifact-smoke" not in snapshot["indices"]["messages"]["items"]
    assert "card-smoke" not in snapshot["indices"]["messages"]["items"]

    assert snapshot["indices"]["turns"]["items"][str(turn_id)]["user_message_id"] == user_message["id"]
    assert assistant_message["id"] in snapshot["indices"]["turns"]["items"][str(turn_id)]["assistant_message_ids"]
    assert stream_id in snapshot["indices"]["turns"]["items"][str(turn_id)]["stream_ids"]
    assert snapshot["indices"]["streams"]["items"][stream_id]["status"] == "completed"
    assert snapshot["indices"]["streams"]["items"][stream_id]["sequence_last"] == 3
    assert snapshot["indices"]["thoughts"]["items"]["thought-smoke"]["thought_id"] == "thought-smoke"
    assert snapshot["indices"]["media"]["items"]["media-smoke"]["media_id"] == "media-smoke"
    assert snapshot["indices"]["cards"]["items"]["card-smoke"]["card_id"] == "card-smoke"
    assert snapshot["indices"]["artifacts"]["items"]["artifact-smoke"]["artifact_id"] == "artifact-smoke"
    assert snapshot["indices"]["wegena"]["items"]["scene-smoke"]["scene_id"] == "scene-smoke"
    assert snapshot["indices"]["workers"]["items"] == {}

    assert Path(snapshot["paths"]["session"]).exists()
    assert Path(snapshot["paths"]["chat"]).exists()
    assert Path(snapshot["paths"]["events"]).exists()
    assert Path(snapshot["paths"]["messages"]).exists()
    assert Path(snapshot["paths"]["turns"]).exists()
    assert Path(snapshot["paths"]["streams"]).exists()
    assert Path(snapshot["paths"]["thoughts"]).exists()
    assert Path(snapshot["paths"]["media"]).exists()
    assert Path(snapshot["paths"]["cards"]).exists()
    assert Path(snapshot["paths"]["artifacts"]).exists()
    assert Path(snapshot["paths"]["wegena"]).exists()

    events_path = Path(tmp_path, "sessions", session_id, "events.jsonl")
    messages_index_path = Path(tmp_path, "sessions", session_id, "messages.index.json")
    assert events_path.exists()
    assert messages_index_path.exists()

    events_lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(events_lines) == 12
    assert status_event["category"] == "status"
    assert reasoning_event["category"] == "reasoning"
    assert media_event["category"] == "media"
    assert artifact_event["category"] == "artifact"
    assert card_event["category"] == "card"
    assert wege_event["category"] == "visual"
    assert complete_stream["category"] == "completion"
    assert complete_legacy["category"] == "legacy"
