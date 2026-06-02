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
        return {"session_id": session_id, "healthy": True, "mode": "reload-smoke"}


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
    (session_dir / "session.json").write_text(
        json.dumps(session.to_dict(), ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    (session_dir / "chat.json").write_text(
        json.dumps(session.history, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )


def test_session_snapshot_reload_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session_id = "snapshot-reload-smoke"
    session = Session(session_id=session_id, source="web")

    _write_session_files(session, Path(tmp_path))

    initial_snapshot = build_session_snapshot(session_id, base_data_dir=str(tmp_path))
    assert initial_snapshot["session_id"] == session_id
    assert initial_snapshot["session"]["session_id"] == session_id
    assert initial_snapshot["chat"] == []
    assert initial_snapshot["events"] == []
    assert initial_snapshot["indices"]["messages"]["items"] == {}
    assert initial_snapshot["indices"]["turns"]["items"] == {}
    assert initial_snapshot["indices"]["streams"]["items"] == {}
    assert initial_snapshot["indices"]["workers"]["items"] == {}
    assert initial_snapshot["indices"]["thoughts"]["items"] == {}
    assert initial_snapshot["indices"]["media"]["items"] == {}
    assert initial_snapshot["indices"]["links"]["items"] == {}
    assert initial_snapshot["indices"]["cards"]["items"] == {}
    assert initial_snapshot["indices"]["artifacts"]["items"] == {}
    assert initial_snapshot["indices"]["playback"]["items"] == {}
    assert initial_snapshot["indices"]["wegena"]["items"] == {}

    user_message = session.add_message("user", "Reload contract user")
    assistant_message = session.add_message(
        "assistant",
        "Reload contract assistant",
        reply_to_message_id=user_message["id"],
        work_id="work-reload",
    )
    turn_id = user_message["turn_id"]
    assert assistant_message["turn_id"] == turn_id
    assert assistant_message["reply_to_message_id"] == user_message["id"]

    pipeline = SessionEventPipeline(session, base_data_dir=str(tmp_path))
    stream_id = "stream-reload"
    work_id = "work-reload"

    assistant_chunk_event = pipeline.process_event(
        {
            "type": "assistant_chunk",
            "session_id": session_id,
            "turn_id": turn_id,
            "stream_id": stream_id,
            "sequence": 1,
            "payload": {"content": "stream part 1"},
        }
    )
    final_chunk_event = pipeline.process_event(
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
    complete_event = pipeline.process_event(
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
                "thought_id": "thought-reload",
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
                "media_id": "media-reload",
                "kind": "voice",
                "mime": "audio/webm",
                "path": "/tmp/media-reload.webm",
                "derived_refs": ["artifact-reload"],
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
                "artifact_id": "artifact-reload",
                "artifact_type": "transcript",
                "path": "/tmp/artifact-reload.txt",
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
                "card_id": "card-reload",
                "card_type": "summary",
                "payload": {"title": "Card reload"},
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
                "scene_id": "scene-reload",
                "scene_type": "reset",
                "composition_ref": "composition-reload",
                "snapshot_ref": "snapshot-reload",
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

    # Reload simulation: the live session object loses its context, but the snapshot must
    # still reconstruct the essential state from disk.
    session.context = {"current_turn_id": 999, "current_turn_user_message_id": "ghost-turn"}
    reloaded_session = Session(session_id=session_id, source="web")
    client = _build_client(reloaded_session, Path(tmp_path))
    response = client.get(f"/api/sessions/{session_id}/snapshot")
    assert response.status_code == 200
    snapshot = response.json()

    direct_snapshot = build_session_snapshot(session_id, base_data_dir=str(tmp_path))

    essential_keys = ("session", "chat", "events", "indices", "paths")
    for key in essential_keys:
        assert snapshot[key] == direct_snapshot[key]

    assert snapshot["session_id"] == session_id
    assert snapshot["session"]["session_id"] == session_id
    assert snapshot["chat"] == session.history
    assert snapshot["indices"]["messages"]["items"][user_message["id"]]["message_id"] == user_message["id"]
    assert snapshot["indices"]["messages"]["items"][assistant_message["id"]]["message_id"] == assistant_message["id"]
    assert snapshot["indices"]["messages"]["items"][assistant_message["id"]]["reply_to_message_id"] == user_message["id"]
    assert snapshot["indices"]["turns"]["items"][str(turn_id)]["user_message_id"] == user_message["id"]
    assert assistant_message["id"] in snapshot["indices"]["turns"]["items"][str(turn_id)]["assistant_message_ids"]
    assert stream_id in snapshot["indices"]["turns"]["items"][str(turn_id)]["stream_ids"]
    assert snapshot["indices"]["turns"]["items"][str(turn_id)]["status"] == "completed"
    assert snapshot["indices"]["streams"]["items"][stream_id]["status"] == "completed"
    assert snapshot["indices"]["streams"]["items"][stream_id]["turn_id"] == turn_id
    assert snapshot["indices"]["streams"]["items"][stream_id]["sequence_last"] == 3
    assert set(snapshot["indices"]["messages"]["items"].keys()) == {user_message["id"], assistant_message["id"]}
    assert len(snapshot["indices"]["messages"]["items"]) == 2

    assert assistant_chunk_event["turn_id"] == turn_id
    assert final_chunk_event["turn_id"] == turn_id
    assert complete_event["turn_id"] == turn_id
    assert status_event["turn_id"] == turn_id
    assert reasoning_event["turn_id"] == turn_id
    assert media_event["turn_id"] == turn_id
    assert artifact_event["turn_id"] == turn_id
    assert card_event["turn_id"] == turn_id
    assert wege_event["turn_id"] == turn_id
    assert complete_legacy["target"] == "legacy"
    assert complete_legacy["category"] == "legacy"

    assert any(event.get("type") == "assistant_chunk" and event.get("turn_id") == turn_id for event in snapshot["events"])
    assert any(event.get("type") == "final_message_chunk" and event.get("turn_id") == turn_id for event in snapshot["events"])
    assert any(event.get("type") == "complete" and event.get("target") == "stream" and event.get("turn_id") == turn_id for event in snapshot["events"])
    assert any(event.get("type") == "status" and event.get("turn_id") == turn_id for event in snapshot["events"])
    assert any(event.get("type") == "complete" and event.get("target") == "legacy" for event in snapshot["events"])

    assert "media-reload" not in snapshot["indices"]["messages"]["items"]
    assert "artifact-reload" not in snapshot["indices"]["messages"]["items"]
    assert "card-reload" not in snapshot["indices"]["messages"]["items"]

    assert snapshot["indices"]["thoughts"]["items"]["thought-reload"]["thought_id"] == "thought-reload"
    assert snapshot["indices"]["media"]["items"]["media-reload"]["media_id"] == "media-reload"
    assert snapshot["indices"]["cards"]["items"]["card-reload"]["card_id"] == "card-reload"
    assert snapshot["indices"]["artifacts"]["items"]["artifact-reload"]["artifact_id"] == "artifact-reload"
    assert snapshot["indices"]["wegena"]["items"]["scene-reload"]["scene_id"] == "scene-reload"
    assert snapshot["indices"]["workers"]["items"] == {}

    # Route-specific current state is a live overlay. The reload contract is about disk-backed essentials.
    assert snapshot["current"]["turn_id"] == 0
    assert snapshot["current"]["legacy_turn_id"] == 0
    assert snapshot["current"]["current_turn_id"] == 0
    assert snapshot["current"]["context"] == {}

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
