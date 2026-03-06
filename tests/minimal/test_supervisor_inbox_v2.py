import pytest
import time
from unittest.mock import MagicMock
from src.core.session import Session
from src.core.orchestrator import AgentOrchestrator

def test_process_worker_events_coalescing():
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("session_1")
    
    # 1. Multiple PROGRESS events for same task should coalesce
    session.publish_event({
        "event_type": "PROGRESS",
        "task_id": "task_1",
        "progress": 0.1,
        "summary": "Step 1"
    })
    session.publish_event({
        "event_type": "PROGRESS",
        "task_id": "task_1",
        "progress": 0.5,
        "summary": "Step 5"
    })
    
    # 2. Critical events should NOT be coalesced
    session.publish_event({
        "event_type": "FAILED",
        "task_id": "task_1",
        "failure_summary": "Error in task"
    })
    
    updates, should_replan = orchestrator._process_worker_events(session)
    
    assert should_replan is True
    # Should have 1 FAILED and 1 PROGRESS (the latest)
    assert len(updates) == 2
    types = [u["event_type"] for u in updates]
    assert "FAILED" in types
    assert "PROGRESS" in types
    
    p_event = next(u for u in updates if u["event_type"] == "PROGRESS")
    assert p_event["progress"] == 0.5

def test_replan_gating_progress_low():
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("session_1")
    
    # PROGRESS with LOW attention should NOT trigger replan
    session.publish_event({
        "event_type": "PROGRESS",
        "task_id": "task_1",
        "attention_level": "low"
    })
    
    _, should_replan = orchestrator._process_worker_events(session)
    assert should_replan is False

def test_replan_gating_attention_medium():
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("session_1")
    
    # Any event with MEDIUM attention should trigger replan
    session.publish_event({
        "event_type": "PROGRESS",
        "task_id": "task_1",
        "attention_level": "medium"
    })
    
    _, should_replan = orchestrator._process_worker_events(session)
    assert should_replan is True

def test_stale_labeling_in_prompt():
    orchestrator = AgentOrchestrator(MagicMock())
    orchestrator.scratchpad_service = MagicMock()
    orchestrator.scratchpad_service.read.return_value = {}
    orchestrator.workspace_service = MagicMock()
    orchestrator.workspace_service.base_dir = "/tmp"
    
    session = Session("session_1")
    session.turn_id = 10
    session.summary = "Old summary"
    
    worker_updates = [
        {
            "event_type": "PROGRESS",
            "task_role": "Searcher",
            "summary": "Looking for files",
            "progress": 0.8,
            "base_turn_id": 8 # 2 turns behind
        }
    ]
    
    # Create a basic prompt and inject updates
    prompt = orchestrator._construct_system_prompt(session, worker_updates=worker_updates)
    
    assert "### Background Worker Updates" in prompt
    assert "[STALE - 2 turns ago] Searcher: Looking for files (80%)" in prompt

def test_failed_not_lost_by_coalescing():
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("session_1")
    
    # Sequence: Progress -> Failed -> Progress (edge case)
    session.publish_event({"event_type": "PROGRESS", "task_id": "t1", "progress": 0.1})
    session.publish_event({"event_type": "FAILED", "task_id": "t1", "failure_summary": "die"})
    session.publish_event({"event_type": "PROGRESS", "task_id": "t1", "progress": 0.2})
    
    updates, _ = orchestrator._process_worker_events(session)
    
    # Should have FAILED and the latest PROGRESS
    assert len(updates) == 2
    types = [u["event_type"] for u in updates]
    assert "FAILED" in types
    assert "PROGRESS" in types
