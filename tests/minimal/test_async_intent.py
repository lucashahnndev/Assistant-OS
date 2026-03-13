import pytest
import time
from unittest.mock import MagicMock, patch
from src.main import Kernel
from src.core.identity import PrincipalContext

@pytest.fixture
def kernel():
    with patch("src.main.check_single_instance"), \
         patch("src.services.llm.manager.LLMManager"), \
         patch("src.services.memory.episodic_memory.EpisodicMemoryService"), \
         patch("src.capabilities.registry.CapabilityRegistry"), \
         patch("src.services.safety_service.SafetyService"), \
         patch("src.core.access_controller.AccessController"), \
         patch("src.core.scheduler.Scheduler"), \
         patch("src.core.worker.WorkerManager"), \
         patch("src.core.orchestrator.AgentOrchestrator"):
        k = Kernel()
        k.scheduler = MagicMock()
        k.worker_manager = MagicMock()
        k.orchestrator = MagicMock()
        return k

def test_process_input_fast_ack(kernel):
    """P1.1: Verify that process_input returns quickly and enqueues work."""
    text = "hello"
    driver = MagicMock()
    
    # Mock scheduler returns a work object
    work = MagicMock()
    work.work_id = "work_123"
    kernel.scheduler.create_work.return_value = work
    
    start_time = time.time()
    work_id = kernel.process_input(text, driver)
    duration = time.time() - start_time
    
    # Assert fast return (< 200ms)
    # Note: In a real environment with many imports, this might be slightly more,
    # but the logic itself should be O(1) LLM-wise.
    assert duration < 0.2, f"Expected fast ACK < 200ms, got {duration*1000:.2f}ms"
    assert work_id == "work_123"
    
    # Assert work was created
    kernel.scheduler.create_work.assert_called_once()
    
    # Assert worker was spawned with initial_plan=None
    args, kwargs = kernel.worker_manager.spawn_worker.call_args
    assert kwargs['initial_plan'] is None
    assert args[0] == "work_123" # work_id
    assert args[2] == text # user_input
    
    # Assert status was sent
    driver.send_status.assert_called()
    call_args = driver.send_status.call_args
    assert call_args[0][1] == 'thinking'
    assert call_args[0][2]['fast_ack'] is True

@patch("src.core.orchestrator.ActionPlan")
@patch("src.core.orchestrator.Session")
def test_orchestrator_adds_user_message_when_async(mock_session_cls, mock_plan_cls, kernel):
    """P1.1: Verify orchestrator adds user message if no initial_plan provided."""
    orch = kernel.orchestrator
    # We want to test the REAl process method logic we added
    from src.core.orchestrator import AgentOrchestrator
    
    # Mock dependencies needed by process()
    orch_instance = AgentOrchestrator()
    orch_instance.i18n = MagicMock()
    orch_instance.config_manager = MagicMock()
    orch_instance.llm_manager = MagicMock()
    orch_instance.intent_resolver_chain = MagicMock()
    orch_instance.access_controller = MagicMock()
    orch_instance.capability_registry = MagicMock()
    
    # Mock session
    session = MagicMock()
    session.history = []
    session.context = {}
    session.pending_action = None
    session.state_summary = {}
    
    user_input = "test message"
    session_id = "test_s"
    
    with patch.object(orch_instance, "get_session_robust", return_value=session), \
         patch.object(orch_instance, "_get_or_create_session_lock"), \
         patch.object(orch_instance, "_save_session"), \
         patch.object(orch_instance, "_detect_user_language", return_value="en"), \
         patch.object(orch_instance, "_get_planner_config", return_value={}), \
         patch.object(orch_instance, "_compute_dynamic_max_steps", return_value=1):
        
        # We need to mock the loop to avoid infinite LLM calls
        # We'll make it return a 'reply' plan immediately
        reply_plan = MagicMock()
        reply_plan.action_id = 'reply'
        reply_plan.response_text = "Hi"
        reply_plan.metadata = {}
        orch_instance.intent_resolver_chain.resolve.return_value = reply_plan
        
        # Run process WITHOUT initial_plan
        orch_instance.process(user_input, session_id=session_id, initial_plan=None)
        
        # Verify message was added to session
        session.add_message.assert_any_call("user", user_input, attachments=None)
        
        # Verify save_session was called
        orch_instance._save_session.assert_called()
