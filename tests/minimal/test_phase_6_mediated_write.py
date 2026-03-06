import pytest
from core.session import Session
from core.orchestrator import AgentOrchestrator
from unittest.mock import MagicMock

def test_mediated_write_approval():
    """Step 2: Verify high-confidence valid-type candidate is accepted."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    
    candidate = {
        "memory_id": "mem_1",
        "memory_type": "fact",
        "scope": "session",
        "content": "Paris is the capital of France",
        "confidence": 0.9,
        "source_type": "worker",
        "status": "candidate"
    }
    
    session.candidate_store = [candidate]
    orchestrator._process_memory_candidates(session)
    
    assert len(session.memory) == 1
    assert session.memory[0]["status"] == "accepted"
    assert session.memory[0]["content"] == "Paris is the capital of France"
    assert len(session.candidate_store) == 0

def test_mediated_write_rejection_low_confidence():
    """Step 2: Verify low-confidence candidate is rejected."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    
    candidate = {
        "memory_id": "mem_2",
        "memory_type": "fact",
        "scope": "session",
        "content": "The moon is made of cheese",
        "confidence": 0.3,
        "source_type": "worker",
        "status": "candidate"
    }
    
    session.candidate_store = [candidate]
    orchestrator._process_memory_candidates(session)
    
    assert len(session.memory) == 0
    # The candidate is drained but not moved to memory
    # We don't currently keep rejected candidates anywhere but log them
    assert len(session.candidate_store) == 0

def test_mediated_write_rejection_invalid_scope():
    """Step 2: Verify type/scope mismatch is rejected."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    
    candidate = {
        "memory_id": "mem_3",
        "memory_type": "task_outcome",
        "scope": "global", # task_outcome only allowed in task/session
        "content": "Task X finished",
        "confidence": 1.0,
        "source_type": "worker",
        "status": "candidate"
    }
    
    session.candidate_store = [candidate]
    orchestrator._process_memory_candidates(session)
    
    assert len(session.memory) == 0

def test_mediated_write_deduplication():
    """Step 2: Verify dedupe prevents duplicate memory entries."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    
    m1 = {
        "memory_id": "mem_4",
        "memory_type": "fact",
        "scope": "session",
        "content": "Water boils at 100C",
        "confidence": 1.0,
        "source_type": "worker",
        "status": "candidate",
        "dedupe_key": "fact:water_boil"
    }
    
    m2 = {
        "memory_id": "mem_5",
        "memory_type": "fact",
        "scope": "session",
        "content": "Water boils at 100 degrees Celsius",
        "confidence": 1.0,
        "source_type": "worker",
        "status": "candidate",
        "dedupe_key": "fact:water_boil" # Same key
    }
    
    session.candidate_store = [m1]
    orchestrator._process_memory_candidates(session)
    assert len(session.memory) == 1
    
    session.candidate_store = [m2]
    orchestrator._process_memory_candidates(session)
    assert len(session.memory) == 1 # Still 1
    assert session.memory[0]["memory_id"] == "mem_4"
