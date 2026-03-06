import pytest
from core.session import Session
from core.worker_runtime import WorkerRuntime
from core.events import WorkerEventType, AttentionLevel

class MockOrchestrator:
    def __init__(self):
        self.sessions = {}
        self.saves = []

    def get_session_robust(self, session_id):
        return self.sessions.get(session_id)

    def _save_session(self, session):
        self.saves.append(session.session_id)

def test_memory_candidate_storage():
    """Step 1: Verify memory candidates go to candidate_store, not event_history."""
    session = Session("test_session")
    orchestrator = MockOrchestrator()
    orchestrator.sessions["test_session"] = session
    
    worker = WorkerRuntime(
        session_id="test_session",
        task_id="task_1",
        run_id="run_1",
        task_role="Researcher",
        turn_id=1,
        base_turn_id=1,
        orchestrator=orchestrator
    )
    
    # Standard event
    worker.report_status(
        event_type=WorkerEventType.PROGRESS,
        phase="testing",
        progress=0.5,
        summary="Halfway there"
    )
    
    # Memory candidate
    worker.report_memory(
        memory_type="fact",
        scope="global",
        content="The sky is blue",
        confidence=0.9,
        metadata={"source": "observation"}
    )
    
    # Assertions
    assert len(session.event_history) == 1
    assert session.event_history[0]["event_type"] == WorkerEventType.PROGRESS
    
    assert len(session.candidate_store) == 1
    candidate = session.candidate_store[0]
    assert candidate["event_type"] == "MEMORY_CANDIDATE"
    assert candidate["content"] == "The sky is blue"
    assert candidate["confidence"] == 0.9
    assert candidate["status"] == "candidate"
    assert candidate["source_type"] == "worker"
    assert candidate["source_id"] == "task_1"

def test_memory_deduplication_in_store():
    """Step 1: Verify memory id prevents duplicate storage in candidate_store."""
    session = Session("test_session")
    
    memory_id = "mem_123"
    event = {
        "memory_id": memory_id,
        "event_type": "MEMORY_CANDIDATE",
        "content": "Unique fact",
        "confidence": 1.0
    }
    
    session.publish_event(event)
    session.publish_event(event) # Duplicate
    
    assert len(session.candidate_store) == 1

def test_worker_standard_events_not_in_candidate_store():
    """Step 1: Ensure standard events don't leak into candidate store."""
    session = Session("test_session")
    
    event = {
        "event_id": "evt_123",
        "event_type": WorkerEventType.COMPLETED,
        "summary": "Done"
    }
    
    session.publish_event(event)
    
    assert len(session.event_history) == 1
    assert len(session.candidate_store) == 0
