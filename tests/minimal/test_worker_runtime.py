import pytest
import time
from core.orchestrator import AgentOrchestrator
from core.session import Session
from core.worker_runtime import WorkerRuntime, WorkerEventType, AttentionLevel

@pytest.fixture
def orchestrator():
    orch = AgentOrchestrator()
    orch.sessions = {}
    # Mock _save_session to avoid IO errors in tests
    orch._save_session = lambda s: None
    return orch

def test_worker_lifecycle_capture(orchestrator):
    """Verify that a successful worker execution captures all phase transitions."""
    session_id = "session_123"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session

    def task_func(worker):
        worker.report_status(
            WorkerEventType.PROGRESS, "processing", 0.5, "Halfway done"
        )
        return "SUCCESS"

    worker = orchestrator.spawn_worker(
        session_id, "Tester", 1, 0, task_func
    )
    
    # Wait for completion
    timeout = 5
    while worker.is_alive() and timeout > 0:
        time.sleep(0.5)
        timeout -= 0.5

    events = session.drain_events()
    event_types = [e["event_type"] for e in events]
    assert "STARTED" in event_types
    assert "PROGRESS" in event_types
    assert "COMPLETED" in event_types
    
    # Verify turned IDs are integers
    assert all(isinstance(e["turn_id"], int) for e in events)

def test_worker_failure_capture(orchestrator):
    """Verify that worker failures emit the correct FAILED event."""
    session_id = "session_fail"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session

    def failing_func(worker):
        raise ValueError("Boom!")

    worker = orchestrator.spawn_worker(
        session_id, "BadWorker", 1, 0, failing_func
    )
    
    time.sleep(1)
    events = session.drain_events()
    assert any(e["event_type"] == "FAILED" for e in events)
    failed_event = next(e for e in events if e["event_type"] == "FAILED")
    assert failed_event["failure_summary"] == "Boom!"
    assert failed_event["attention_level"] == "high"

def test_worker_slow_signal(orchestrator):
    """Verify that SLOW signals are emitted if progress stalls."""
    session_id = "session_slow"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session

    def stalling_func(worker):
        time.sleep(2) # Exceed threshold
        return "DONE"

    # Use a low threshold for the test
    worker = WorkerRuntime(
        session_id=session_id,
        task_id="slow_task",
        run_id="run_1",
        task_role="Staller",
        turn_id=1,
        base_turn_id=0,
        orchestrator=orchestrator,
        slow_threshold_seconds=1.0 # 1 second threshold
    )
    worker.spawn(stalling_func)
    
    time.sleep(2.5) # Wait for monitor to trigger
    
    events = session.drain_events()
    assert any(e["event_type"] == "SLOW" for e in events)
    slow_event = next(e for e in events if e["event_type"] == "SLOW")
    assert slow_event["attention_level"] == "medium"
    assert "Stalled in phase" in slow_event["summary"]

def test_summary_truncation(orchestrator):
    """Verify that long summaries are truncated."""
    session_id = "session_trunc"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    long_summary = "A" * 1000
    
    def long_task(worker):
        worker.report_status(WorkerEventType.PROGRESS, "p", 0.5, long_summary)

    worker = orchestrator.spawn_worker(session_id, "Truncer", 1, 0, long_task)
    time.sleep(0.5)
    
    events = session.drain_events()
    progress_event = next(e for e in events if e["event_type"] == "PROGRESS")
    assert len(progress_event["summary"]) <= 500
    assert progress_event["summary"].endswith("...")
