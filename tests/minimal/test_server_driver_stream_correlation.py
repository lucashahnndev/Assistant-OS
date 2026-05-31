import asyncio
import json
import os
import sys
import threading
from types import SimpleNamespace

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

from drivers.interfaces.server_driver import ServerDriver


def _make_driver():
    driver = ServerDriver.__new__(ServerDriver)
    driver.interface_id = "web"
    driver.kernel = SimpleNamespace(
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
    assert late_event["stream_id"] == first_event["stream_id"]
    assert first_event["sequence"] < late_event["sequence"]
    assert "type" in complete_event
    assert "stream_id" in complete_event

    context["current_turn_user_message_id"] = "user-msg-2"
    driver.send_response("new turn response", target="session-1", is_chunk=True)
    new_turn_payload = driver._captured_messages[3][1]
    new_turn_event = json.loads(new_turn_payload)

    assert new_turn_event["stream_id"] != first_event["stream_id"]
    assert new_turn_event["sequence"] == 0
