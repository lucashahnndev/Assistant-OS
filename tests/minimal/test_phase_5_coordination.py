import pytest
import time
from core.orchestrator import AgentOrchestrator
from core.session import Session
from core.worker_runtime import WorkerEventType, AttentionLevel

@pytest.fixture
def orchestrator():
    orch = AgentOrchestrator()
    orch.sessions = {}
    orch._save_session = lambda s: None
    return orch

def test_concurrent_tasks_prioritization(orchestrator):
    """Verify that multiple concurrent events are prioritized and limited."""
    session_id = "conc_1"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    # Spawn two workers
    def task_a(worker):
        worker.report_status(WorkerEventType.COMPLETED, "done", 1.0, "Task A finished")
        
    def task_b(worker):
        worker.report_status(WorkerEventType.FAILED, "error", 0.0, "Task B failed")

    worker_a = orchestrator.spawn_worker(session_id, "WorkerA", 1, 0, task_a)
    worker_b = orchestrator.spawn_worker(session_id, "WorkerB", 1, 0, task_b)
    
    # Wait for completion (poll)
    timeout = 5
    while timeout > 0:
        if any(t.get("status") in {"COMPLETED", "FAILED"} for t in session.task_registry.values() if t["task_id"] in {worker_a.task_id, worker_b.task_id}):
            # Wait a bit more for second worker if only one finished
            if all(t.get("status") in {"COMPLETED", "FAILED"} for t in session.task_registry.values() if t["task_id"] in {worker_a.task_id, worker_b.task_id}):
                break
        time.sleep(0.5)
        timeout -= 0.5
    
    # Process events
    updates, _ = orchestrator._process_worker_events(session)
    decisions = orchestrator._decide_on_worker_events(session, updates)
    
    print(f"\nUPDATES: {updates}")
    print(f"DECISIONS: {decisions}")

    # We expect both to be considered
    outcomes = [d["outcome"] for d in decisions]
    assert any(o in {"CHAT", "PANEL"} for o in outcomes)
    assert len(decisions) >= 2

def test_intent_supersede_logic(orchestrator):
    """Verify that tasks in the same intent group are superseded."""
    session_id = "sup_1"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    def long_task(worker):
        time.sleep(1.5)
        worker.report_status(WorkerEventType.COMPLETED, "done", 1.0, "Old Task finished")

    # Spawn task 1 with group "search"
    worker_1 = orchestrator.spawn_worker(session_id, "Searcher", 1, 0, long_task, intent_group_id="search")
    
    # Spawn task 2 with same group "search"
    worker_2 = orchestrator.spawn_worker(session_id, "SearcherV2", 1, 0, lambda w: None, intent_group_id="search")
    
    # Registry check
    assert session.task_registry[worker_1.task_id]["is_superseded"] is True
    assert session.task_registry[worker_2.task_id]["is_superseded"] is False

    # Ensure worker 1 event is ignored in decisions
    time.sleep(2.0)
    updates, _ = orchestrator._process_worker_events(session)
    decisions = orchestrator._decide_on_worker_events(session, updates)
    
    # worker 1's COMPLETED event should be skipped because it is superseded
    worker_1_decisions = [d for d in decisions if d["event"]["task_id"] == worker_1.task_id]
    assert len(worker_1_decisions) == 0

def test_focus_affects_scoring(orchestrator):
    """Verify that active focus increases the score and likelihood of CHAT outcome."""
    session_id = "focus_1"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    # Set focus to group "writing"
    session.active_focus_group = "writing"
    
    # Event from focused task
    event_focused = {
        "task_id": "task_focused",
        "task_role": "Writer",
        "event_type": "COMPLETED",
        "summary": "Draft ready",
        "intent_group_id": "writing",
        "base_turn_id": 0
    }
    
    # Event from non-focused task
    event_other = {
        "task_id": "task_other",
        "task_role": "Researcher",
        "event_type": "COMPLETED",
        "summary": "Info found",
        "intent_group_id": "research",
        "base_turn_id": 0
    }
    
    # Manually publish to Registry
    session.publish_event(event_focused)
    session.publish_event(event_other)
    
    decisions = orchestrator._decide_on_worker_events(session, [event_focused, event_other])
    
    d_focused = next(d for d in decisions if d["event"]["task_id"] == "task_focused")
    d_other = next(d for d in decisions if d["event"]["task_id"] == "task_other")
    
    assert d_focused["score"] > d_other["score"]
    assert d_focused["outcome"] == "CHAT"

def test_spam_prevention(orchestrator):
    """Verify that CHAT outcomes are capped."""
    session_id = "spam_1"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    events = []
    for i in range(5):
        e = {
            "task_id": f"t_{i}",
            "task_role": f"Worker_{i}",
            "event_type": "COMPLETED",
            "summary": "Done",
            "attention_level": "high",
            "base_turn_id": 0
        }
        events.append(e)
        session.publish_event(e)
        
    decisions = orchestrator._decide_on_worker_events(session, events)
    chat_count = sum(1 for d in decisions if d["outcome"] == "CHAT")
    assert chat_count <= 2

def test_intent_isolation(orchestrator):
    """Verify that same role with different intent does NOT supersede."""
    session_id = "iso_1"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    # Task 1: "research" intent
    worker_1 = orchestrator.spawn_worker(session_id, "Researcher", 1, 0, lambda w: None, intent_group_id="topic_a")
    
    # Task 2: "research" role, but "topic_b" intent
    worker_2 = orchestrator.spawn_worker(session_id, "Researcher", 1, 0, lambda w: None, intent_group_id="topic_b")
    
    assert session.task_registry[worker_1.task_id]["is_superseded"] is False
    assert session.task_registry[worker_2.task_id]["is_superseded"] is False

def test_stale_but_relevant_not_silenced(orchestrator):
    """Verify that a stale task which is focused remains visible."""
    session_id = "stale_rel_1"
    session = Session(session_id=session_id)
    session.turn_id = 5
    orchestrator.sessions[session_id] = session
    
    # Focused task
    session.active_focus_task_id = "t_stale"
    
    event = {
        "task_id": "t_stale",
        "task_role": "Helper",
        "event_type": "COMPLETED",
        "summary": "Late but focused",
        "base_turn_id": 1 # 4 turns stale
    }
    session.publish_event(event) # Registry updated
    
    decisions = orchestrator._decide_on_worker_events(session, [event])
    assert decisions[0]["outcome"] == "CHAT" # Focused overrides staleness penalty

def test_waiting_input_no_hijack(orchestrator):
    """Verify that WAITING_INPUT from unrelated task is downgraded to CHAT and doesn't steal focus."""
    session_id = "hijack_1"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    # Current focus
    session.active_focus_task_id = "t_main"
    
    # Unrelated input request (not focused)
    event_side = {
        "task_id": "t_side",
        "task_role": "Background",
        "event_type": "WAITING_INPUT",
        "summary": "Need key",
        "base_turn_id": 0,
        "timestamp": "2026-03-06T00:00:00Z"
    }
    
    # Focused progress (focused)
    event_main = {
        "task_id": "t_main",
        "task_role": "Main",
        "event_type": "COMPLETED",
        "summary": "Finished important thing",
        "base_turn_id": 0,
        "timestamp": "2026-03-06T00:00:01Z"
    }
    
    session.publish_event(event_side)
    session.publish_event(event_main)
    
    decisions = orchestrator._decide_on_worker_events(session, [event_side, event_main])
    
    # Sort order: Focus wins.
    assert decisions[0]["role"] == "Main"
    assert decisions[1]["role"] == "Background"
    
    # Outcomes: Main is focused -> CHAT (COMPLETED doesn't become INPUT).
    # Side is NOT focused -> CHAT (WAITING_INPUT is downgraded from INPUT to CHAT because not focused).
    assert decisions[0]["outcome"] == "CHAT"
    assert decisions[1]["outcome"] == "CHAT"

def test_deterministic_tie_break(orchestrator):
    """Verify tie-break: focus > distance > priority > timestamp."""
    session_id = "tie_1"
    session = Session(session_id=session_id)
    session.turn_id = 10
    orchestrator.sessions[session_id] = session
    
    # Event A: Turn distance 1, COMPLETED, Newer
    event_a = {
        "task_id": "ta", "task_role": "A", "event_type": "COMPLETED", 
        "base_turn_id": 9, "timestamp": "2026-03-06T01:00:00Z"
    }
    # Event B: Turn distance 2, WAITING_INPUT (higher priority), Older
    event_b = {
        "task_id": "tb", "task_role": "B", "event_type": "WAITING_INPUT", 
        "base_turn_id": 8, "timestamp": "2026-03-06T00:30:00Z"
    }
    # Event C: Turn distance 1, COMPLETED, Older
    event_c = {
        "task_id": "tc", "task_role": "C", "event_type": "COMPLETED", 
        "base_turn_id": 9, "timestamp": "2026-03-06T00:00:00Z"
    }
    
    for e in [event_a, event_b, event_c]: session.publish_event(e)
    
    decisions = orchestrator._decide_on_worker_events(session, [event_a, event_b, event_c])
    
    # Distance beats Priority: A and C (dist 1) beat B (dist 2)
    # Timestamp beats between A and C: A (newer) beats C (older)
    assert decisions[0]["role"] == "A"
    assert decisions[1]["role"] == "C"
    assert decisions[2]["role"] == "B"

def test_waiting_input_downgrade(orchestrator):
    """Verify that excess CHAT/INPUT events are downgraded to PANEL, including WAITING_INPUT."""
    session_id = "down_1"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    # 3 High priority events
    events = [
        {"task_id": "t1", "task_role": "T1", "event_type": "COMPLETED", "base_turn_id": 0, "timestamp": "03", "attention_level": "high"},
        {"task_id": "t2", "task_role": "T2", "event_type": "COMPLETED", "base_turn_id": 0, "timestamp": "02", "attention_level": "high"},
        {"task_id": "t3", "task_role": "T3", "event_type": "WAITING_INPUT", "base_turn_id": 0, "timestamp": "01"},
    ]
    for e in events: session.publish_event(e)
    
    decisions = orchestrator._decide_on_worker_events(session, events)
    
    # Order by Priority: T3 (WAITING_INPUT = 5) > T1/T2 (COMPLETED = 3)
    # Between T1 and T2: T1 (timestamp "03") > T2 (timestamp "02")
    assert decisions[0]["role"] == "T3"
    assert decisions[1]["role"] == "T1"
    assert decisions[2]["role"] == "T2"
    
    # Outcomes:
    # T3 is 1st -> CHAT (not focused so not INPUT)
    # T1 is 2nd -> CHAT
    # T2 is 3rd -> PANEL (downgraded from CHAT)
    assert decisions[0]["outcome"] == "CHAT"
    assert decisions[1]["outcome"] == "CHAT"
    assert decisions[2]["outcome"] == "PANEL"
