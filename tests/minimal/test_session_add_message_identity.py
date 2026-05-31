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


def test_assistant_message_can_reply_to_user_message_without_reusing_identity():
    session = Session(session_id="test-session")

    user_msg = session.add_message("user", "hello world")
    assistant_msg = session.add_message(
        "assistant",
        "hi there",
        reply_to_message_id=user_msg["id"],
    )

    legacy_assistant_msg = session.add_message("assistant", "orphan reply")

    assert assistant_msg["id"] != user_msg["id"]
    assert assistant_msg["reply_to_message_id"] == user_msg["id"]
    assert legacy_assistant_msg["id"]
    assert "reply_to_message_id" not in legacy_assistant_msg
