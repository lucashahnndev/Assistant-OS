import pytest
from unittest.mock import MagicMock
from core.session import Session
from core.orchestrator import AgentOrchestrator

def test_retrieval_opt_in_explicit_recall():
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    session.memory = [
        {
            "memory_id": "m1",
            "content": "User likes blue",
            "memory_type": "preference",
            "scope": "session",
            "status": "accepted"
        }
    ]
    
    # Explicit recall keyword "lembra"
    memory = orchestrator._retrieve_relevant_memory(session, "Você lembra da minha cor favorita?")
    assert len(memory) == 1
    assert memory[0]["content"] == "User likes blue"

def test_retrieval_opt_in_complex_input():
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    session.memory = [
        {
            "memory_id": "m1",
            "content": "Project X is active",
            "memory_type": "fact",
            "scope": "session",
            "status": "accepted"
        }
    ]
    
    # Complex input (> 50 chars)
    complex_input = "I need to start working on the new module for the architecture we discussed earlier today during the meeting."
    assert len(complex_input) > 50
    memory = orchestrator._retrieve_relevant_memory(session, complex_input)
    assert len(memory) == 1

def test_retrieval_opt_out_simple_greeting():
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    session.memory = [
        {"memory_id": "m1", "content": "Secret info", "memory_type": "fact", "scope": "session", "status": "accepted"}
    ]
    
    # Simple greeting
    memory = orchestrator._retrieve_relevant_memory(session, "Olá!")
    assert len(memory) == 0

def test_retrieval_limit_recent():
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test_session")
    # Add 10 memory items
    session.memory = [
        {"memory_id": f"m{i}", "content": f"Fact {i}", "memory_type": "fact", "scope": "session", "status": "accepted"}
        for i in range(10)
    ]
    
    memory = orchestrator._retrieve_relevant_memory(session, "Recall everything.")
    assert len(memory) == 5
    assert memory[-1]["memory_id"] == "m9"
    assert memory[0]["memory_id"] == "m5"
