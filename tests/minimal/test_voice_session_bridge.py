import asyncio
import json
import sys
import threading
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
    driver.loop = asyncio.new_event_loop()
    driver.loop_ready = threading.Event()
    driver.loop_ready.set()

    captured = []

    async def send_personal_message(message, session_id):
        captured.append((session_id, message))

    driver.connection_manager = SimpleNamespace(send_personal_message=send_personal_message)
    driver._captured_messages = captured
    return driver


def test_voice_semantics_are_canonical_and_share_the_reserved_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("AOSD_DATA_DIR", str(tmp_path))

    session = Session(session_id="voice-bridge", source="web")
    driver = _build_driver(session, Path(tmp_path))

    def _run_coro(coro, loop):
        loop.run_until_complete(coro)
        return SimpleNamespace()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _run_coro)

    reserved_turn_id = driver.reserve_canonical_turn(session.session_id, role="user")
    assert reserved_turn_id is not None
    assert session.context["current_turn_id"] == reserved_turn_id
    assert session.context["current_turn_reserved_for"] == "user"

    transcript_id = f"{session.session_id}:{reserved_turn_id}"
    transcript_event = driver.send_voice_event(
        session.session_id,
        {
            "type": "asr.final",
            "turnId": reserved_turn_id,
            "text": "oi",
            "content": "oi",
            "transcriptId": transcript_id,
        },
    )

    user_message = session.add_message("user", "oi")
    assert user_message["turn_id"] == reserved_turn_id

    assistant_message = session.add_message(
        "assistant",
        "Olá",
        reply_to_message_id=user_message["id"],
    )
    assert assistant_message["turn_id"] == reserved_turn_id

    voice_state_event = driver.send_voice_event(
        session.session_id,
        {"type": "voice.state", "state": "listening", "turnId": reserved_turn_id},
    )
    orb_event = driver.send_voice_event(
        session.session_id,
        {"type": "orb.intensity", "intensity": 0.42, "turnId": reserved_turn_id},
    )

    playback_id = f"playback-{reserved_turn_id}"
    playback_start = driver.send_voice_event(
        session.session_id,
        {
            "type": "tts.start",
            "turnId": reserved_turn_id,
            "playbackId": playback_id,
            "text": "Olá",
        },
    )
    playback_chunk = driver.send_voice_event(
        session.session_id,
        {
            "type": "tts.chunk",
            "turnId": reserved_turn_id,
            "playbackId": playback_id,
            "seq": 1,
            "b64": "AA==",
        },
    )
    playback_end = driver.send_voice_event(
        session.session_id,
        {
            "type": "tts.end",
            "turnId": reserved_turn_id,
            "playbackId": playback_id,
        },
    )

    session.context["current_response_stream_id"] = f"stream-{reserved_turn_id}"
    session.context["current_response_stream_turn_id"] = reserved_turn_id
    session.context["current_response_stream_user_message_id"] = user_message["id"]
    session.context["current_response_stream_sequence"] = 2
    driver.send_complete(session.session_id)
    complete_payload = json.loads(driver._captured_messages[-1][1])

    _write_session_files(session, Path(tmp_path))
    snapshot = build_session_snapshot(session.session_id, base_data_dir=str(tmp_path))

    assert transcript_event["type"] == "transcript.final"
    assert transcript_event["turn_id"] == reserved_turn_id
    assert transcript_event["transcript_id"] == transcript_id
    assert voice_state_event["category"] == "status"
    assert voice_state_event["turn_id"] == reserved_turn_id
    assert orb_event["category"] == "visual"
    assert orb_event["turn_id"] == reserved_turn_id
    assert playback_start["type"] == "playback.started"
    assert playback_start["turn_id"] == reserved_turn_id
    assert playback_start["playback_id"] == playback_id
    assert playback_chunk["type"] == "playback.chunk"
    assert playback_chunk["turn_id"] == reserved_turn_id
    assert playback_end["type"] == "playback.completed"
    assert playback_end["turn_id"] == reserved_turn_id
    assert complete_payload["type"] == "complete"
    assert complete_payload["target"] == "stream"
    assert complete_payload["turn_id"] == reserved_turn_id
    assert complete_payload["stream_id"] == f"stream-{reserved_turn_id}"

    events = snapshot["events"]
    event_types = [event["type"] for event in events]
    assert "transcript.final" in event_types
    assert "voice.state" in event_types
    assert "orb.intensity" in event_types
    assert "playback.started" in event_types
    assert "playback.chunk" in event_types
    assert "playback.completed" in event_types
    assert "complete" in event_types

    transcript_index = snapshot["indices"]["transcripts"]["items"][transcript_id]
    assert transcript_index["turn_id"] == reserved_turn_id
    assert transcript_index["message_id"] == user_message["id"]
    assert transcript_index["content"] == "oi"
    assert transcript_index["source"] == "voice"
    assert transcript_index["status"] == "final"

    playback_index = snapshot["indices"]["playback"]["items"][playback_id]
    assert playback_index["turn_id"] == reserved_turn_id
    assert playback_index["message_id"] == assistant_message["id"]
    assert playback_index["status"] == "completed"
    assert playback_index["chunk_count"] == 1

    turn_index = snapshot["indices"]["turns"]["items"][str(reserved_turn_id)]
    assert user_message["id"] == turn_index["user_message_id"]
    assert assistant_message["id"] in turn_index["assistant_message_ids"]
    assert transcript_id in turn_index["transcript_ids"]
    assert playback_id in turn_index["playback_ids"]
    assert turn_index["is_active"] is False

    chat_roles = [message["role"] for message in snapshot["chat"]]
    assert chat_roles == ["user", "assistant"]
