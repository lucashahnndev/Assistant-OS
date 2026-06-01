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
    (session_dir / "session.json").write_text(
        json.dumps(session.to_dict(), ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    (session_dir / "chat.json").write_text(
        json.dumps(session.history, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )


def test_session_turn_snapshot_contract_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session_id = "turn-snapshot-smoke"
    session = Session(session_id=session_id, source="web")

    user_message = session.add_message("user", "Hello canonical turn")
    assistant_message = session.add_message(
        "assistant",
        "Canonical turn acknowledged.",
        reply_to_message_id=user_message["id"],
        work_id="work-turn-smoke",
    )

    turn_id = user_message["turn_id"]
    assert assistant_message["turn_id"] == turn_id
    assert assistant_message["id"] != user_message["id"]
    assert assistant_message["reply_to_message_id"] == user_message["id"]

    pipeline = SessionEventPipeline(session, base_data_dir=str(tmp_path))
    stream_id = "stream-turn-smoke"
    work_id = "work-turn-smoke"

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

    orphan_session = SimpleNamespace(session_id="orphan-turn-smoke")
    orphan_pipeline = SessionEventPipeline(orphan_session, base_data_dir=str(tmp_path))
    orphan_event = orphan_pipeline.process_event(
        {
            "type": "status",
            "session_id": "orphan-turn-smoke",
            "payload": {"message": "legacy status"},
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
    assert direct_snapshot["indices"]["turns"]["items"][str(turn_id)]["user_message_id"] == user_message["id"]

    assert snapshot["session_id"] == session_id
    assert snapshot["session"]["session_id"] == session_id
    assert snapshot["chat"] == session.history
    assert snapshot["current"]["turn_id"] == turn_id
    assert snapshot["current"]["current_turn_id"] == turn_id
    assert snapshot["current"]["legacy_turn_id"] == session.turn_id
    assert snapshot["indices"]["turns"]["items"][str(turn_id)]["user_message_id"] == user_message["id"]
    assert assistant_message["id"] in snapshot["indices"]["turns"]["items"][str(turn_id)]["assistant_message_ids"]
    assert user_message["id"] in snapshot["indices"]["turns"]["items"][str(turn_id)]["message_ids"]
    assert assistant_message["id"] in snapshot["indices"]["turns"]["items"][str(turn_id)]["message_ids"]
    assert stream_id in snapshot["indices"]["turns"]["items"][str(turn_id)]["stream_ids"]
    assert snapshot["indices"]["turns"]["items"][str(turn_id)]["status"] == "completed"
    assert snapshot["indices"]["streams"]["items"][stream_id]["status"] == "completed"
    assert snapshot["indices"]["streams"]["items"][stream_id]["turn_id"] == turn_id
    assert snapshot["indices"]["streams"]["items"][stream_id]["sequence_last"] == 3
    assert snapshot["indices"]["messages"]["items"][user_message["id"]]["turn_id"] == turn_id
    assert snapshot["indices"]["messages"]["items"][assistant_message["id"]]["turn_id"] == turn_id
    assert snapshot["indices"]["messages"]["items"][assistant_message["id"]]["reply_to_message_id"] == user_message["id"]
    assert len(snapshot["indices"]["turns"]["items"]) == 1
    assert len(snapshot["indices"]["messages"]["items"]) == 2

    assert assistant_chunk_event["turn_id"] == turn_id
    assert final_chunk_event["turn_id"] == turn_id
    assert complete_event["turn_id"] == turn_id
    assert status_event["turn_id"] == turn_id
    assert orphan_event.get("turn_id") is None

    assert snapshot["events"][0]["turn_id"] == turn_id
    assert snapshot["events"][1]["turn_id"] == turn_id
    assert any(event.get("type") == "assistant_chunk" and event.get("turn_id") == turn_id for event in snapshot["events"])
    assert any(event.get("type") == "final_message_chunk" and event.get("turn_id") == turn_id for event in snapshot["events"])
    assert any(event.get("type") == "complete" and event.get("target") == "stream" and event.get("turn_id") == turn_id for event in snapshot["events"])
    assert any(event.get("type") == "status" and event.get("turn_id") == turn_id for event in snapshot["events"])

    assert Path(snapshot["paths"]["session"]).exists()
    assert Path(snapshot["paths"]["chat"]).exists()
    assert Path(snapshot["paths"]["events"]).exists()
    assert Path(snapshot["paths"]["messages"]).exists()
    assert Path(snapshot["paths"]["turns"]).exists()
    assert Path(snapshot["paths"]["streams"]).exists()

    orphan_snapshot = build_session_snapshot("orphan-turn-smoke", base_data_dir=str(tmp_path))
    assert orphan_snapshot["indices"]["turns"]["items"] == {}
    assert orphan_event["category"] == "status"
    assert orphan_event.get("turn_id") is None
    assert orphan_snapshot["events"][-1]["type"] == "status"
    assert orphan_snapshot["events"][-1].get("turn_id") is None

