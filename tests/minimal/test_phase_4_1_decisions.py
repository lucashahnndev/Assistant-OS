import pytest
from src.core.orchestrator import AgentOrchestrator
from src.core.session import Session
import uuid
import os

@pytest.fixture
def orchestrator():
    return AgentOrchestrator()

@pytest.fixture
def session(tmp_path):
    # Mocking session with history and turn_id
    session_id = str(uuid.uuid4())
    session_dir = tmp_path / "sessions" / session_id
    session_dir.mkdir(parents=True)
    
    s = Session(session_id)
    s.turn_id = 10
    return s

def test_decide_outcomes_by_type_and_attention(orchestrator, session):
    # 1. PROGRESS with low attention should be SILENT or PANEL
    event_low = {
        "event_type": "PROGRESS",
        "attention_level": "LOW",
        "summary": "Working...",
        "task_role": "Expert",
        "base_turn_id": 10
    }
    decisions = orchestrator._decide_on_worker_events(session, [event_low])
    assert len(decisions) == 1
    assert decisions[0]["outcome"] == "SILENT" # LOW attention progress is silent

    # 2. PROGRESS with high attention should be PANEL
    event_high = {
        "event_type": "PROGRESS",
        "attention_level": "HIGH",
        "summary": "Almost done!",
        "task_role": "Expert",
        "base_turn_id": 10
    }
    decisions = orchestrator._decide_on_worker_events(session, [event_high])
    assert decisions[0]["outcome"] == "PANEL"

    # 3. WAITING_INPUT should be INPUT/CHAT
    event_input = {
        "event_type": "WAITING_INPUT",
        "attention_level": "HIGH",
        "summary": "Need API key",
        "task_role": "SecretKeeper",
        "base_turn_id": 10
    }
    decisions = orchestrator._decide_on_worker_events(session, [event_input])
    assert decisions[0]["outcome"] == "INPUT"

def test_stale_event_downgrade(orchestrator, session):
    # Event from 2 turns ago
    stale_event = {
        "event_type": "COMPLETED",
        "attention_level": "HIGH",
        "summary": "Finished old task",
        "task_role": "Ghost",
        "base_turn_id": 8 # session.turn_id is 10
    }
    decisions = orchestrator._decide_on_worker_events(session, [stale_event])
    assert decisions[0]["outcome"] == "PANEL" # Downgraded from CHAT because stale

def test_history_pollution_prevention(orchestrator, session):
    # This test verifies that _decide_on_worker_events itself doesn't add to history
    # and that the orchestrator loop (mocked or conceptual) wouldn't either.
    event = {
        "event_type": "COMPLETED",
        "attention_level": "HIGH",
        "summary": "Success",
        "task_role": "Worker",
        "base_turn_id": 10
    }
    initial_history_len = len(session.history)
    orchestrator._decide_on_worker_events(session, [event])
    assert len(session.history) == initial_history_len
    
def test_slow_event_policy(orchestrator, session):
    event_slow = {
        "event_type": "SLOW",
        "attention_level": "MEDIUM",
        "summary": "I'm stuck",
        "task_role": "Sloth",
        "base_turn_id": 10
    }
    decisions = orchestrator._decide_on_worker_events(session, [event_slow])
    assert decisions[0]["outcome"] == "PANEL" # Usually state/panel, not chat
