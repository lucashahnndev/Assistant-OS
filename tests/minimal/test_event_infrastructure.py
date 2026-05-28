import pytest
import datetime
from core.session import Session
from core.events import WorkerEvent, WorkerEventType, AttentionLevel

def test_worker_event_schema_normalization():
    """Verify that WorkerEvent handles the normalized schema correctly."""
    event = WorkerEvent(
        task_id="task_1",
        run_id="run_1",
        task_role="Tester",
        turn_id=1,      # Integer
        base_turn_id=0, # Integer
        event_type=WorkerEventType.STARTED, # Uppercase enum
        phase="init",
        progress=0.0,
        summary="Testing schema"
    )
    
    data = event.to_dict()
    assert data["turn_id"] == 1
    assert data["event_type"] == "STARTED"
    assert isinstance(data["event_id"], str)
    assert isinstance(data["timestamp"], str)

def test_session_event_inbox_auto_fill():
    """Verify that Session.publish_event fills missing ID/Timestamp."""
    session = Session(session_id="test_session")
    
    minimal_event = {
        "task_id": "task_1",
        "event_type": "PROGRESS",
        "phase": "work",
        "progress": 0.5,
        "summary": "Working..."
    }
    
    session.publish_event(minimal_event)
    
    published = session.drain_events()
    assert len(published) == 1
    assert "event_id" in published[0]
    assert "timestamp" in published[0]

def test_worker_event_deduplication():
    session = Session(session_id="test_session")
    event_id = "unique_id"
    
    event = {
        "event_id": event_id,
        "task_id": "task_1",
        "event_type": "STARTED",
        "phase": "init",
        "progress": 0.0,
        "summary": "Original"
    }
    
    session.publish_event(event)
    session.publish_event(event) # Duplicate
    
    events = session.drain_events()
    assert len(events) == 1
    assert events[0]["summary"] == "Original"


def test_non_memory_event_with_memory_id_is_not_suppressed_by_candidate_store():
    session = Session(session_id="test_session")

    session.publish_event({
        "event_id": "cand-1",
        "event_type": "MEMORY_CANDIDATE",
        "memory_id": "memory-1",
        "summary": "candidate",
    })
    session.publish_event({
        "event_id": "evt-1",
        "event_type": "PROGRESS",
        "memory_id": "memory-1",
        "summary": "normal event",
    })

    events = session.drain_events()
    assert len(events) == 1
    assert events[0]["summary"] == "normal event"

def test_session_event_history_ring_buffer():
    session = Session(session_id="test_session")
    # Fill beyond default ring buffer (assuming small for test or just checking limit)
    # Let's say we want to keep 100, but Session might use collections.deque(maxlen=100)
    for i in range(110):
        session.publish_event({
            "event_id": f"id_{i}",
            "summary": f"event {i}"
        })
    
    # Check that it didn't grow indefinitely
    assert len(session.event_history) <= 100

def test_session_drain_events():
    session = Session(session_id="test_session")
    session.publish_event({"event_id": "1", "summary": "e1"})
    session.publish_event({"event_id": "2", "summary": "e2"})
    
    drained = session.drain_events()
    assert len(drained) == 2
    assert drained[0]["event_id"] == "1"
    
    # Second drain should be empty
    assert len(session.drain_events()) == 0

def test_worker_event_validation_error():
    """Verify pydantic validation for progress and timestamp."""
    with pytest.raises(Exception):
        WorkerEvent(
            task_id="t1", run_id="r1", task_role="r", 
            turn_id=1, base_turn_id=0,
            event_type=WorkerEventType.STARTED, phase="p",
            progress=1.5, # Out of range
            summary="error"
        )
