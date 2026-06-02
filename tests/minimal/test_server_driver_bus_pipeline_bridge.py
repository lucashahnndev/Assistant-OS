import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.session import Session
from core.session_event_pipeline import build_session_snapshot
from drivers.interfaces.server_driver import ServerDriver


class _OrchestratorStub:
    def __init__(self, session):
        self._session = session

    def get_session_robust(self, session_id):
        if session_id == self._session.session_id:
            return self._session
        return None


class _KernelStub:
    def __init__(self, session, base_data_dir: Path):
        self.orchestrator = _OrchestratorStub(session)
        self.config_manager = SimpleNamespace(base_data_dir=str(base_data_dir))


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


def _build_driver(session: Session, base_data_dir: Path):
    driver = ServerDriver.__new__(ServerDriver)
    driver.kernel = _KernelStub(session, base_data_dir)
    driver.interface_id = "web"
    return driver


def test_server_driver_bus_events_are_canonicalized_by_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session = Session(session_id="bridge-smoke", source="web")
    user_message = session.add_message("user", "Bridge user")
    assistant_message = session.add_message(
        "assistant",
        "Bridge assistant",
        reply_to_message_id=user_message["id"],
        work_id="work-bridge",
    )
    turn_id = user_message["turn_id"]
    assert assistant_message["turn_id"] == turn_id

    driver = _build_driver(session, Path(tmp_path))

    worker_event = driver._bridge_bus_event_through_pipeline(
        {
            "type": "worker_state",
            "session_id": session.session_id,
            "turn_id": turn_id,
            "work_id": "work-bridge",
            "payload": {
                "status": "completed",
                "label": "Worker finished",
                "last_thought": "all good",
            },
        }
    )
    health_event = driver._bridge_bus_event_through_pipeline(
        {
            "type": "system_health",
            "session_id": session.session_id,
            "turn_id": turn_id,
            "payload": {
                "status": "degraded",
                "message": "backend health probe",
            },
        }
    )
    weg_event = driver._bridge_bus_event_through_pipeline(
        {
            "type": "weg_scene_reset",
            "session_id": session.session_id,
            "turn_id": turn_id,
            "payload": {
                "scene_id": "scene-bridge",
                "scene_type": "reset",
                "composition_ref": "composition-bridge",
                "snapshot_ref": "snapshot-bridge",
                "status": "ok",
            },
        }
    )
    media_event = driver._bridge_bus_event_through_pipeline(
        {
            "type": "media.added",
            "session_id": session.session_id,
            "turn_id": turn_id,
            "message_id": assistant_message["id"],
            "work_id": "work-bridge",
            "payload": {
                "media_id": "media-bridge",
                "kind": "voice",
                "mime": "audio/webm",
                "path": "/tmp/media-bridge.webm",
            },
        }
    )
    artifact_event = driver._bridge_bus_event_through_pipeline(
        {
            "type": "artifact.created",
            "session_id": session.session_id,
            "turn_id": turn_id,
            "message_id": assistant_message["id"],
            "work_id": "work-bridge",
            "payload": {
                "artifact_id": "artifact-bridge",
                "artifact_type": "transcript",
                "path": "/tmp/artifact-bridge.txt",
                "summary": "artifact summary",
                "status": "ready",
            },
        }
    )
    card_event = driver._bridge_bus_event_through_pipeline(
        {
            "type": "card.created",
            "session_id": session.session_id,
            "turn_id": turn_id,
            "message_id": assistant_message["id"],
            "work_id": "work-bridge",
            "payload": {
                "card_id": "card-bridge",
                "card_type": "summary",
                "payload": {"title": "Card bridge"},
                "pinned": True,
                "ttl": 300,
            },
        }
    )
    visual_intent_event = driver._bridge_bus_event_through_pipeline(
        {
            "type": "assistant_visual_intent",
            "session_id": session.session_id,
            "payload": {
                "mode": "concept_orbit",
                "intent": "show the architecture",
                "background_policy": "adaptive",
                "source": "atlas_reply_plan",
            },
        }
    )
    direct_pipeline_event = driver._bridge_bus_event_through_pipeline(
        {
            "type": "message_added",
            "session_id": session.session_id,
            "_pipeline_recorded": True,
            "payload": {"message_id": "skip-me"},
        }
    )

    _write_session_files(session, Path(tmp_path))

    snapshot = build_session_snapshot(session.session_id, base_data_dir=str(tmp_path))

    assert worker_event["category"] == "worker"
    assert health_event["category"] == "status"
    assert weg_event["category"] == "visual"
    assert media_event["category"] == "media"
    assert artifact_event["category"] == "artifact"
    assert card_event["category"] == "card"
    assert visual_intent_event["category"] == "visual"
    assert direct_pipeline_event is None

    assert snapshot["indices"]["workers"]["items"]["work-bridge"]["status"] == "completed"
    assert snapshot["indices"]["wegena"]["items"]["scene-bridge"]["scene_id"] == "scene-bridge"
    assert snapshot["indices"]["media"]["items"]["media-bridge"]["media_id"] == "media-bridge"
    assert snapshot["indices"]["artifacts"]["items"]["artifact-bridge"]["artifact_id"] == "artifact-bridge"
    assert snapshot["indices"]["cards"]["items"]["card-bridge"]["card_id"] == "card-bridge"
    assert snapshot["indices"]["messages"]["items"][user_message["id"]]["message_id"] == user_message["id"]
    assert snapshot["indices"]["messages"]["items"][assistant_message["id"]]["message_id"] == assistant_message["id"]
    assert "media-bridge" not in snapshot["indices"]["messages"]["items"]
    assert "artifact-bridge" not in snapshot["indices"]["messages"]["items"]
    assert "card-bridge" not in snapshot["indices"]["messages"]["items"]

    event_types = [event.get("type") for event in snapshot["events"]]
    assert "worker_state" in event_types
    assert "system_health" in event_types
    assert "weg_scene_reset" in event_types
    assert "media.added" in event_types
    assert "artifact.created" in event_types
    assert "card.created" in event_types
    assert "assistant_visual_intent" in event_types
