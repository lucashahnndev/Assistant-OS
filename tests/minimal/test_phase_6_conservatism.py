import pytest
import os
import json
import tempfile
from core.session import Session

def test_session_memory_serialization():
    """Step 3: Verify session memory persists through to_dict/from_dict."""
    session = Session("test_persist")
    memory_item = {
        "memory_id": "mem_p1",
        "memory_type": "fact",
        "scope": "session",
        "content": "User likes coffee",
        "confidence": 1.0,
        "status": "accepted"
    }
    session.memory = [memory_item]
    
    # Serialize
    data = session.to_dict()
    assert "memory" in data
    assert data["memory"][0]["content"] == "User likes coffee"
    
    # Deserialize
    new_session = Session.from_dict(data)
    assert len(new_session.memory) == 1
    assert new_session.memory[0]["memory_id"] == "mem_p1"

def test_global_memory_disabled_gate():
    """Step 3: Verify global memory is rejected by policy."""
    from core.orchestrator import AgentOrchestrator
    from unittest.mock import MagicMock
    
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_gate")
    
    candidate = {
        "memory_id": "mem_g1",
        "memory_type": "fact",
        "scope": "global",
        "content": "A global fact",
        "confidence": 1.0,
        "source_type": "worker",
        "status": "candidate"
    }
    
    session.candidate_store = [candidate]
    orchestrator._process_memory_candidates(session)
    
    assert len(session.memory) == 0
    # Check if it was rejected specifically for being global (simulation of log/state check)
    # Since we drain it, we can check the status in the local reference
    assert candidate["status"] == "rejected"
    assert "Global memory scope is currently disabled" in candidate["reason"]

def test_session_persistence_simulation():
    """Step 3: Verify turn-over-turn persistence simulation."""
    session = Session("test_turns")
    session.turn_id = 1
    session.memory = [{"id": "m1", "content": "turn 1 fact"}]
    
    # Simulate turn increment
    session.turn_id += 1
    
    # Ensure memory is still there
    assert len(session.memory) == 1
    assert session.memory[0]["content"] == "turn 1 fact"
