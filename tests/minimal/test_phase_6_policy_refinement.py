import pytest
from unittest.mock import MagicMock
from core.session import Session
from core.orchestrator import AgentOrchestrator

def test_retrieval_resolved_by_history():
    """Verify continuity marker resolved by recent history doesn't trigger lookup."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    session.history = [{"role": "user", "content": "Open the architectural file"}]
    session.memory = [{"content": "Old config", "memory_type": "fact", "status": "accepted", "confidence": 0.9}]
    
    # Input has auxiliary marker 'it'
    memory = orchestrator._retrieve_relevant_memory(session, "Read it again.")
    # Should NOT trigger because 'architectural file' is in recent history (simulated by 'file' heuristic)
    assert len(memory) == 0

def test_retrieval_explicit_recall():
    """Verify explicit recall triggers lookup."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    session.memory = [{"content": "Important fact", "memory_type": "fact", "status": "accepted", "confidence": 0.9}]
    
    memory = orchestrator._retrieve_relevant_memory(session, "What do you remember about the project?")
    assert len(memory) == 1

def test_retrieval_ranking_and_limit():
    """Verify ranking (recency priority) and max 5 limit."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    session.memory = [
        {"content": f"Fact {i}", "memory_type": "fact", "status": "accepted", "confidence": 0.8}
        for i in range(10)
    ]
    
    memory = orchestrator._retrieve_relevant_memory(session, "Recall all facts.")
    assert len(memory) == 5
    # Recency ranking: Fact 9 should be first (scored higher)
    assert memory[0]["content"] == "Fact 9"

def test_acceptance_preference_strict():
    """Verify preference needs 0.9 + source_id + high relevance."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    
    # Needs high relevance
    candidate = {
        "memory_type": "preference",
        "scope": "session",
        "content": "User likes dark mode",
        "confidence": 0.95,
        "source_id": "sup_1",
        "relevance": "medium" 
    }
    
    orchestrator._evaluate_memory_candidate(session, candidate)
    assert candidate["status"] == "rejected"
    assert "additional policy criteria" in candidate["reason"]

def test_acceptance_fact_provenance():
    """Verify fact needs source_id."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    
    candidate = {
        "memory_type": "fact",
        "scope": "session",
        "content": "Python is 3.12",
        "confidence": 0.85
    }
    
    orchestrator._evaluate_memory_candidate(session, candidate)
    assert candidate["status"] == "rejected"
    assert "Provenance required" in candidate["reason"]

def test_acceptance_task_outcome():
    """Verify task_outcome needs COMPLETED status."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    
    candidate = {
        "memory_type": "task_outcome",
        "scope": "session",
        "content": "Build successful",
        "confidence": 0.75,
        "task_status": "FAILED"
    }
    
    orchestrator._evaluate_memory_candidate(session, candidate)
    assert candidate["status"] == "rejected"

def test_context_deduplication():
    """Verify deduplication against recent history."""
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    session.history = [{"role": "assistant", "content": "I successfully finished the migration."}]
    session.memory = [
        {"content": "I successfully finished the migration.", "memory_type": "summary", "status": "accepted", "confidence": 0.9, "source_id": "s1"}
    ]
    
    memory = orchestrator._retrieve_relevant_memory(session, "Recall history.")
    assert len(memory) == 0 # Deduplicated
