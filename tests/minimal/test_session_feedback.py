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
from core.session_event_pipeline import build_session_snapshot
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
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="admin", username="tester", id="user-1")
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


def test_session_feedback_like_dislike_upsert_and_snapshot_exposes_feedback(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session = Session(session_id="feedback-smoke", source="web")
    user_message = session.add_message("user", "hello feedback")
    assistant_message = session.add_message(
        "assistant",
        "final answer for feedback",
        reply_to_message_id=user_message["id"],
        work_id="work-feedback",
    )
    _write_session_files(session, Path(tmp_path))

    client = _build_client(session, Path(tmp_path))
    like_response = client.post(
        f"/api/sessions/{session.session_id}/messages/{assistant_message['id']}/feedback",
        json={"rating": "like", "reason": None, "comment": "clear answer"},
    )
    assert like_response.status_code == 200
    like_payload = like_response.json()
    assert like_payload["status"] == "success"
    assert like_payload["feedback"]["rating"] == "like"
    assert like_payload["feedback"]["session_id"] == session.session_id
    assert like_payload["feedback"]["turn_id"] == assistant_message["turn_id"]
    assert like_payload["feedback"]["message_id"] == assistant_message["id"]

    dislike_response = client.post(
        f"/api/sessions/{session.session_id}/messages/{assistant_message['id']}/feedback",
        json={"rating": "dislike", "reason": "too short", "comment": "needs more detail"},
    )
    assert dislike_response.status_code == 200
    dislike_payload = dislike_response.json()
    assert dislike_payload["feedback"]["rating"] == "dislike"
    assert dislike_payload["feedback"]["message_id"] == assistant_message["id"]
    assert dislike_payload["feedback"]["turn_id"] == assistant_message["turn_id"]

    snapshot = build_session_snapshot(session.session_id, base_data_dir=str(tmp_path))
    feedback_items = snapshot["indices"]["feedback"]["items"]
    assert len(feedback_items) == 1
    feedback_record = feedback_items[f"{session.session_id}:{assistant_message['id']}"]
    assert feedback_record["session_id"] == session.session_id
    assert feedback_record["turn_id"] == assistant_message["turn_id"]
    assert feedback_record["message_id"] == assistant_message["id"]
    assert feedback_record["rating"] == "dislike"
    assert feedback_record["reason"] == "too short"
    assert feedback_record["comment"] == "needs more detail"
    assert feedback_record["source"] == "chat"
    assert feedback_record["user_id"] == "user-1"

    chat_path = Path(tmp_path) / "sessions" / session.session_id / "chat.json"
    assert json.loads(chat_path.read_text(encoding="utf-8")) == session.history
    assert snapshot["chat"] == session.history
    assert any(event.get("type") == "message.feedback.updated" for event in snapshot["events"])
    assert all(msg.get("id") != f"{session.session_id}:{assistant_message['id']}" for msg in snapshot["chat"])
    assert assistant_message["id"] in snapshot["indices"]["messages"]["items"]
    assert snapshot["indices"]["messages"]["items"][assistant_message["id"]]["role"] == "assistant"


def test_session_feedback_rejects_non_assistant_targets_and_missing_index_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session = Session(session_id="feedback-guard", source="web")
    user_message = session.add_message("user", "hello feedback")
    thought = session.add_thought("internal reasoning", work_id="work-feedback", message_id=user_message["id"], source="reasoning")
    _write_session_files(session, Path(tmp_path))

    client = _build_client(session, Path(tmp_path))
    response = client.post(
        f"/api/sessions/{session.session_id}/messages/{thought['id']}/feedback",
        json={"rating": "like", "reason": None, "comment": None},
    )
    assert response.status_code == 404

    initial_snapshot = build_session_snapshot("feedback-empty", base_data_dir=str(tmp_path))
    assert initial_snapshot["indices"]["feedback"]["items"] == {}
    assert initial_snapshot["paths"]["feedback"].endswith("feedback.index.json")
    assert initial_snapshot["chat"] == []
    assert initial_snapshot["events"] == []
