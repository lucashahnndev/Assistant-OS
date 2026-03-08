import pytest
import uuid
import os
import json
from src.core.orchestrator import AgentOrchestrator
from src.core.session import Session

from unittest.mock import MagicMock, patch

def test_structured_decision_trace():
    with patch('src.core.orchestrator.LLMManager'), \
         patch('src.core.orchestrator.SkillLoader'), \
         patch('src.core.orchestrator.ConfigManager'), \
         patch('src.core.orchestrator.SessionIndexManager'):
        orchestrator = AgentOrchestrator()
    
    session = Session(session_id="test_tracing")
    session.turn_id = 1
    
    # Mock some events for arbitration
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "WAITING_INPUT",
        "task_id": "task_123",
        "task_role": "SearchWorker",
        "summary": "Need credentials",
        "attention_level": "high",
        "timestamp": "2026-03-06T12:00:00Z"
    }
    
    # Manually populate task registry for context
    session.task_registry["task_123"] = {
        "task_id": "task_123",
        "task_role": "SearchWorker",
        "status": "WAITING_INPUT",
        "base_turn_id": 0,
        "is_relevant_to_current_focus": True
    }
    session.active_focus_task_id = "task_123"
    
    # Trigger arbitration
    decisions = orchestrator._decide_on_worker_events(session, [event])
    
    # Verify traces were recorded
    assert hasattr(session, "decision_traces")
    assert len(session.decision_traces) > 0
    
    trace = session.decision_traces[0]
    assert trace["decision_type"] == "EVENT_COORDINATION"
    assert trace["selected_outcome"] == "INPUT" # Focused WAITING_INPUT -> INPUT
    assert trace["task_id"] == "task_123"
    assert "scoring_factors" in trace
    assert trace["scoring_factors"]["final_score"] >= 80 # (50 focus + 30 waiting_input)
    assert len(trace["candidate_events"]) == 1
    assert trace["candidate_events"][0]["event_id"] == event["event_id"]

def test_memory_trace_generation():
    with patch('src.core.orchestrator.LLMManager'), \
         patch('src.core.orchestrator.SkillLoader'), \
         patch('src.core.orchestrator.ConfigManager'), \
         patch('src.core.orchestrator.SessionIndexManager'):
        orchestrator = AgentOrchestrator()
        
    session = Session(session_id="test_memory_tracing")
    session.turn_id = 1
    
    candidate = {
        "memory_id": "mem_123",
        "memory_type": "fact",
        "content": "User likes dark mode",
        "confidence": 0.9,
        "task_id": "task_abc",
        "dedupe_key": "fact_user_likes_dark_mode"
    }
    
    # Manually trigger evaluation
    orchestrator._evaluate_memory_candidate(session, candidate)
    
    # Find the ACCEPTED trace
    traces = [t for t in session.decision_traces if t["decision_type"] == "MEMORY_RETRIEVAL"]
    assert len(traces) > 0
    
    trace = traces[0]
    assert trace["selected_outcome"] == "ACCEPTED"
    assert trace["scoring_factors"]["confidence"] == 0.9
    assert trace["reason_codes"] == ["policy_match"]

if __name__ == "__main__":
    pytest.main([__file__])
