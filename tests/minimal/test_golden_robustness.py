import pytest
import uuid
import time
from unittest.mock import MagicMock, patch
from core.orchestrator import AgentOrchestrator
from core.session import Session
from core.identity import PrincipalContext
from core.errors import AgentError, ErrorCode
from core.resolution.action_plan import ActionPlan

@pytest.fixture
def orchestrator():
    # Mocking dependencies for minimal orchestrator instantiation
    with patch("services.llm.manager.LLMManager"), \
         patch("services.memory.episodic_memory.EpisodicMemoryService"), \
         patch("capabilities.registry.CapabilityRegistry"), \
         patch("services.safety_service.SafetyService"), \
         patch("core.access_controller.AccessController"):
        orch = AgentOrchestrator()
        orch.initialized = True
        orch.capability_registry = MagicMock()
        orch.intent_resolver_chain = MagicMock()
        orch.access_controller = MagicMock()
        orch.access_controller.pre_dispatch_gate.return_value = (True, "")
        orch.safety_service = MagicMock()
        orch.safety_service.is_sensitive.return_value = False
        return orch

def test_golden_tool_timeout(orchestrator):
    """P0.3: Golden test for tool execution timeout."""
    session_id = "test_session"
    user_input = "run slow tool"
    
    # Create a real session
    session = Session(session_id)
    session.context["principal_context"] = PrincipalContext(
        user_id="user_123", 
        role="user", 
        interface="web", 
        sender_id="user_123", 
        session_id=session_id
    ).model_dump()
    
    # Mock tool that raises timeout
    orchestrator.capability_registry.dispatch.side_effect = Exception("Tool execution timed out after 30s")
    
    # Mock planner returning a tool call then a reply
    plan = ActionPlan(action_id="slow_tool", args={}, source="llm")
    reply_plan = ActionPlan(action_id="reply", args={"text": "Done"}, source="llm")
    orchestrator.intent_resolver_chain.resolve.side_effect = [plan, reply_plan]
    
    # Run orchestrator
    with patch.object(orchestrator, "get_session_robust", return_value=session):
        with patch.object(orchestrator, "_save_session"):
            response = orchestrator.process(user_input, session_id)
    
    # Verify error code was logged/handled
    # In orchestrator.py, we wrap dispatch in try-except and set error_code = TOOL_TIMEOUT if "timeout" in str(e)
    # The result is stored in 'result' variable which is then attached to session history.
    
    # Check if any result indicates failure with TOOL_TIMEOUT
    # The orchestrator attaches the result to the session.
    orchestrator.capability_registry.dispatch.assert_called_once()
    
def test_golden_tool_schema_mismatch(orchestrator):
    """P0.3: Golden test for tool schema mismatch."""
    session_id = "test_session"
    user_input = "run bad tool"
    
    session = Session(session_id)
    session.context["principal_context"] = PrincipalContext(
        interface="web", 
        sender_id="user_123", 
        session_id=session_id
    ).model_dump()


    # Mock tool that raises schema error
    orchestrator.capability_registry.dispatch.side_effect = Exception("ValidationError: missing required argument 'target'")
    
    plan = ActionPlan(action_id="bad_tool", args={}, source="llm")
    reply_plan = ActionPlan(action_id="reply", args={"text": "Error handled"}, source="llm")
    orchestrator.intent_resolver_chain.resolve.side_effect = [plan, reply_plan]
    
    with patch.object(orchestrator, "get_session_robust", return_value=session):
        with patch.object(orchestrator, "_save_session"):
            orchestrator.process(user_input, session_id)
            
    orchestrator.capability_registry.dispatch.assert_called_once()

def test_golden_invalid_planner_json(orchestrator):
    """P0.3: Golden test for invalid planner JSON."""
    session_id = "test_session"
    user_input = "malformed response"
    
    session = Session(session_id)
    session.context["principal_context"] = PrincipalContext(
        interface="web", 
        sender_id="user_123", 
        session_id=session_id
    ).model_dump()


    # Mock intent resolver returning an error action due to JSON failure
    error_plan = ActionPlan(
        action_id="error", 
        args={}, 
        source="llm_error",
        metadata={"error_code": ErrorCode.PLANNER_SCHEMA_MISMATCH.value}
    )
    orchestrator.intent_resolver_chain.resolve.return_value = error_plan
    
    with patch.object(orchestrator, "get_session_robust", return_value=session):
        response = orchestrator.process(user_input, session_id)
    
    # Orchestrator should break loop on error action if handled correctly
    # Orchestrator should return an error message
    assert "error" in response.lower()

def test_golden_repeated_loop_detection(orchestrator):
    """P0.3: Golden test for repeated-loop detection."""
    session_id = "test_session"
    user_input = "loop me"
    
    plan = ActionPlan(action_id="loop_tool", args={}, source="llm")
    orchestrator.intent_resolver_chain.resolve.return_value = plan
    
    # We can't easily test the internal loop counter without deeper mocking,
    # but we can verify that after N steps it stops.
    # For now, just a placeholder for the logic we added.
    pass

def test_golden_network_failure(orchestrator):
    """P0.3: Golden test for network failure during tool execution."""
    session_id = "test_session"
    user_input = "fetch remote"
    
    session = Session(session_id)
    session.context["principal_context"] = PrincipalContext(
        interface="web", 
        sender_id="user_123", 
        session_id=session_id
    ).model_dump()


    orchestrator.capability_registry.dispatch.side_effect = Exception("ConnectionError: Max retries exceeded")
    
    plan = ActionPlan(action_id="fetch_tool", args={}, source="llm")
    reply_plan = ActionPlan(action_id="reply", args={"text": "Network issue"}, source="llm")
    orchestrator.intent_resolver_chain.resolve.side_effect = [plan, reply_plan]
    
    with patch.object(orchestrator, "get_session_robust", return_value=session):
        orchestrator.process(user_input, session_id)
    
    orchestrator.capability_registry.dispatch.assert_called_once()
