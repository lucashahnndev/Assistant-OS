import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

from core.session import Session


def test_add_message_returns_canonical_message_and_history_entry():
    session = Session(session_id="test-session")

    msg = session.add_message("user", "hello world")

    assert isinstance(msg, dict)
    assert msg["role"] == "user"
    assert msg["content"] == "hello world"
    assert msg["id"]
    assert session.history[-1]["id"] == msg["id"]
    assert session.turn_id == 1
