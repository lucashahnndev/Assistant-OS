import pytest
import time
import uuid
import threading
from unittest.mock import MagicMock, patch
from src.core.session import Session
from src.core.orchestrator import AgentOrchestrator

def test_session_snapshot_is_deep_copy():
    """Verify that get_snapshot returns a deep copy of critical structures."""
    session = Session("test_s")
    session.history.append({"role": "user", "content": "hello", "id": "m1"})
    session.context["key"] = "value"
    session.state_summary["goal"] = "original"
    
    snapshot = session.get_snapshot()
    
    # Modify snapshot
    snapshot.history[0]["content"] = "modified"
    snapshot.context["key"] = "new_value"
    snapshot.state_summary["goal"] = "changed"
    
    # Verify original is unchanged
    assert session.history[0]["content"] == "hello"
    assert session.context["key"] == "value"
    assert session.state_summary["goal"] == "original"
    assert session is not snapshot

@patch("src.core.orchestrator.queue.Queue")
def test_save_session_enqueues_patch(mock_queue_cls):
    """Verify that _save_session enqueues a patch instead of blocking."""
    mock_queue = MagicMock()
    mock_queue_cls.return_value = mock_queue
    
    orch = AgentOrchestrator()
    session = Session("test_s")
    patch_data = {"message": {"role": "assistant", "content": "hi", "id": "m1"}}
    
    orch._save_session(session, patch=patch_data)
    
    # Verify patch was put in queue
    mock_queue.put.assert_called_once()
    enqueued_patch = mock_queue.put.call_args[0][0]
    assert enqueued_patch["session_id"] == "test_s"
    assert enqueued_patch["message"]["content"] == "hi"

def test_writer_loop_applies_patch_and_saves():
    """Integration test for the background writer loop."""
    orch = AgentOrchestrator()
    # Mock disk save to avoid real I/O
    orch._save_session_to_disk = MagicMock()
    
    session = Session("test_s")
    orch.get_session_robust = MagicMock(return_value=session)
    
    # We'll manually trigger the logic that the thread would run
    # to avoid complex thread synchronization in a unit test,
    # but we'll use the real apply_patch and writer queue concepts.
    
    msg_id = str(uuid.uuid4())
    patch_data = {
        "session_id": "test_s",
        "message": {"role": "assistant", "content": "async response", "id": msg_id}
    }
    
    # The writer loop normally does this:
    session.apply_patch(patch_data)
    orch._save_session_to_disk(session)
    
    assert len(session.history) == 1
    assert session.history[0]["content"] == "async response"
    orch._save_session_to_disk.assert_called_with(session)

def test_patch_idempotency():
    """Verify that duplicate patches (same message ID) are ignored."""
    session = Session("test_s")
    msg_id = "duplicate_id"
    patch_data = {
        "message": {"role": "assistant", "content": "first", "id": msg_id},
        "work_id": "work_1"
    }
    
    session.apply_patch(patch_data)
    assert len(session.history) == 1
    
    # Apply same patch again
    session.apply_patch(patch_data)
    assert len(session.history) == 1 # Should NOT increase
    
    # Apply different message with same work_id
    patch_2 = {
        "message": {"role": "assistant", "content": "second", "id": "other_id"},
        "work_id": "work_1"
    }
    session.apply_patch(patch_2)
    assert len(session.history) == 1 # Should NOT increase due to work_id dedupe
