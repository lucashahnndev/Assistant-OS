import pytest
from unittest.mock import MagicMock
from core.orchestrator import AgentOrchestrator
from core.session import Session

@pytest.fixture
def orchestrator():
    orch = AgentOrchestrator()
    orch.sessions = {}
    orch._save_session = MagicMock()
    orch.intent_resolver_chain = MagicMock()
    orch.skill_registry = MagicMock()
    # Mock skill registry to accept any action for testing
    orch.skill_registry.get_skill_for_action.return_value = MagicMock()
    orch.skill_registry.resolve_action_id.side_effect = lambda x: x
    # Mock i18n and other services if needed
    orch.i18n = MagicMock()
    orch.i18n.t.return_value = "Thinking..."
    return orch

def test_supervisor_reacts_to_worker_events(orchestrator):
    """Verify that Supervisor drains events and adds them to history."""
    session_id = "test_inbox"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    # Simulate a worker event in the inbox
    session.publish_event({
        "event_type": "COMPLETED",
        "task_role": "Researcher",
        "summary": "Found the data",
        "base_turn_id": 0
    })
    
    # Mock the LLM to return a "finish" action to stop the loop
    mock_plan = MagicMock()
    mock_plan.action_id = "final_response"
    mock_plan.args = {"text": "Acknowledged"}
    mock_plan.metadata = {}
    orchestrator.intent_resolver_chain.resolve.return_value = mock_plan
    
    # process normally returns the final response
    orchestrator.process("Hello", session_id=session_id)
    
    # Verify history contains the worker update
    system_msgs = [m for m in session.history if m["role"] == "system"]
    assert any("Researcher COMPLETED: Found the data" in m["content"] for m in system_msgs)
    
def test_supervisor_stale_event_labeling(orchestrator):
    """Verify that events from old turns are labeled as [STALE]."""
    session_id = "test_stale"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    # Advance session turn manually
    session.turn_id = 10
    
    # Simulate an event from turn 0
    session.publish_event({
        "event_type": "PROGRESS",
        "task_role": "OldWorker",
        "summary": "Still working",
        "base_turn_id": 0 # Very old
    })
    
    mock_plan = MagicMock()
    mock_plan.action_id = "final_response"
    mock_plan.args = {"text": "OK"}
    mock_plan.metadata = {}
    orchestrator.intent_resolver_chain.resolve.return_value = mock_plan
    
    orchestrator.process("Check status", session_id=session_id)
    
    system_msgs = [m for m in session.history if m["role"] == "system"]
    stale_msg = next(m for m in system_msgs if "OldWorker" in m["content"])
    assert "[STALE]" in stale_msg["content"]

def test_supervisor_reset_plan_on_event(orchestrator):
    """Verify that plan is reset to None if background events are found during loop."""
    session_id = "test_reset"
    session = Session(session_id=session_id)
    orchestrator.sessions[session_id] = session
    
    # We'll use a side effect to publish an event WHILE the loop is running
    # but since it's synchronous in process, we can't easily do it mid-loop
    # unless we mock resolve to do it.
    
    event_published = False
    
    def resolve_side_effect(*args, **kwargs):
        nonlocal event_published
        if not event_published:
            # Publish event during first call
            session.publish_event({
                "event_type": "PROGRESS",
                "task_role": "MidLoop",
                "summary": "Mid-turn update",
                "base_turn_id": session.turn_id
            })
            event_published = True
            # Return some plan
            p = MagicMock()
            p.action_id = "some_action"
            p.thought = "Thinking..."
            p.args = {}
            p.metadata = {}
            return p
        else:
            # Return final plan
            p = MagicMock()
            p.action_id = "final_response"
            p.args = {"text": "Done"}
            p.metadata = {}
            return p

    orchestrator.intent_resolver_chain.resolve.side_effect = resolve_side_effect
    
    orchestrator.process("Loop check", session_id=session_id)
    
    # If it worked, resolve should have been called at least twice 
    # (once initially, and once after the event was detected mid-loop)
    assert orchestrator.intent_resolver_chain.resolve.call_count >= 2
    
    # Verify the event info was added
    assert any("MidLoop: Mid-turn update" in m["content"] for m in session.history if m["role"] == "system")
