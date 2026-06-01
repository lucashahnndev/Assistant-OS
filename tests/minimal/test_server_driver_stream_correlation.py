import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

from drivers.interfaces.server_driver import ServerDriver


def _make_driver(base_data_dir=None):
    driver = ServerDriver.__new__(ServerDriver)
    driver.interface_id = "web"
    driver.kernel = SimpleNamespace(
        config_manager=SimpleNamespace(base_data_dir=base_data_dir) if base_data_dir else SimpleNamespace(),
        orchestrator=SimpleNamespace(
            get_session_robust=lambda session_id: None
        )
    )
    driver.loop = asyncio.new_event_loop()
    driver.loop_ready = threading.Event()
    driver.loop_ready.set()

    captured = []

    async def send_personal_message(message, session_id):
        captured.append((session_id, message))

    driver.connection_manager = SimpleNamespace(send_personal_message=send_personal_message)
    driver._captured_messages = captured
    return driver


def test_stream_reuse_survives_complete_until_turn_changes(monkeypatch):
    driver = _make_driver()
    context = {
        "current_turn_user_message_id": "user-msg-1",
        "current_turn_id": 1,
    }
    session = SimpleNamespace(context=context)
    driver.kernel.orchestrator.get_session_robust = lambda session_id: session

    def _run_coro(coro, loop):
        loop.run_until_complete(coro)
        return SimpleNamespace()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _run_coro)

    driver.send_response("first response", target="session-1", is_chunk=True)
    driver.send_complete("session-1")
    driver.send_response("late chunk", target="session-1", is_chunk=True)

    first_payload = driver._captured_messages[0][1]
    complete_payload = driver._captured_messages[1][1]
    late_payload = driver._captured_messages[2][1]

    first_event = json.loads(first_payload)
    complete_event = json.loads(complete_payload)
    late_event = json.loads(late_payload)

    assert first_event["type"] == "final_message_chunk"
    assert first_event["stream_id"] == complete_event["stream_id"]
    assert first_event["turn_id"] == 1
    assert complete_event["turn_id"] == 1
    assert late_event["stream_id"] == first_event["stream_id"]
    assert late_event["turn_id"] == 1
    assert first_event["sequence"] < late_event["sequence"]
    assert "type" in complete_event
    assert "stream_id" in complete_event

    context["current_turn_user_message_id"] = "user-msg-2"
    context["current_turn_id"] = 2
    driver.send_response("new turn response", target="session-1", is_chunk=True)
    new_turn_payload = driver._captured_messages[3][1]
    new_turn_event = json.loads(new_turn_payload)

    assert new_turn_event["stream_id"] != first_event["stream_id"]
    assert new_turn_event["sequence"] == 0
    assert new_turn_event["turn_id"] == 2


def test_complete_uses_stream_target_and_falls_back_without_stream(monkeypatch):
    driver = _make_driver()
    session = SimpleNamespace(
        context={
            "current_turn_user_message_id": "user-msg-1",
            "current_turn_id": 1,
        }
    )
    driver.kernel.orchestrator.get_session_robust = lambda session_id: session

    def _run_coro(coro, loop):
        loop.run_until_complete(coro)
        return SimpleNamespace()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _run_coro)

    driver.send_response("first response", target="session-1", is_chunk=True)
    driver.send_complete("session-1")

    first_event = json.loads(driver._captured_messages[0][1])
    complete_event = json.loads(driver._captured_messages[1][1])
    assert complete_event["type"] == "complete"
    assert complete_event["event_type"] == "complete"
    assert complete_event["target"] == "stream"
    assert complete_event["stream_id"] == first_event["stream_id"]
    assert complete_event["turn_id"] == 1

    driver.send_response("late chunk", target="session-1", is_chunk=True)
    late_event = json.loads(driver._captured_messages[2][1])
    assert late_event["stream_id"] == complete_event["stream_id"]
    assert late_event["turn_id"] == 1

    session.context.pop("current_response_stream_id", None)
    session.context.pop("current_response_stream_sequence", None)
    session.context.pop("current_response_stream_user_message_id", None)
    session.context.pop("current_response_stream_turn_id", None)
    driver.send_complete("session-1")
    fallback_complete_event = json.loads(driver._captured_messages[3][1])
    assert fallback_complete_event["type"] == "complete"
    assert fallback_complete_event["event_type"] == "complete"
    assert fallback_complete_event["target"] == "legacy"
    assert fallback_complete_event["legacy"] is True
    assert fallback_complete_event["ambiguous"] is True
    assert fallback_complete_event["turn_id"] == 1
    assert "stream_id" not in fallback_complete_event
    assert "message_id" not in fallback_complete_event


def test_live_events_are_persisted_through_pipeline(tmp_path, monkeypatch):
    driver = _make_driver(str(tmp_path))
    session = SimpleNamespace(
        session_id="session-1",
        context={
            "current_turn_user_message_id": "user-msg-1",
            "current_turn_id": 1,
        },
        event_timeline=[],
    )
    driver.kernel.orchestrator.get_session_robust = lambda session_id: session

    def _run_coro(coro, loop):
        loop.run_until_complete(coro)
        return SimpleNamespace()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _run_coro)

    driver.send_response("first response", target="session-1", is_chunk=True)
    driver.send_status("session-1", "thinking", {"label": "Working"})
    driver.send_complete("session-1")

    events_path = Path(tmp_path, "sessions", "session-1", "events.jsonl")
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4

    events = [json.loads(line) for line in lines]
    event_types = [event["type"] for event in events]
    assert event_types[0] == "final_message_chunk"
    assert event_types[1] == "assistant_chunk"
    assert event_types[2] == "status"
    assert event_types[3] == "complete"

    assert events[0]["event_type"] == "final_message_chunk"
    assert events[1]["event_type"] == "assistant_chunk"
    assert events[2]["event_type"] == "status"
    assert events[3]["event_type"] == "complete"
    assert events[3]["target"] == "stream"
    assert events[3]["stream_id"] == events[0]["stream_id"]
    assert events[0]["turn_id"] == 1
    assert events[1]["turn_id"] == 1
    assert events[2]["turn_id"] == 1
    assert events[3]["turn_id"] == 1
    assert events[0]["sequence"] == 0
    assert events[1]["sequence"] == 1
    assert events[2]["category"] == "status"
    assert events[3]["category"] == "completion"

    messages_index_path = Path(tmp_path, "sessions", "session-1", "messages.index.json")
    assert not messages_index_path.exists()

    streams_index = json.loads(Path(tmp_path, "sessions", "session-1", "streams.index.json").read_text(encoding="utf-8"))

    assert streams_index["items"][events[0]["stream_id"]]["status"] == "completed"
    assert streams_index["items"][events[0]["stream_id"]]["sequence_last"] == 2
