import pytest
from unittest.mock import MagicMock
from src.core.orchestrator import AgentOrchestrator

@pytest.fixture
def orchestrator():
    # Mock config
    mock_config = MagicMock()
    mock_config.get.return_value = 10.0
    mock_config.base_data_dir = "/tmp/assistant_test"
    
    AgentOrchestrator._instance = None
    orch = AgentOrchestrator(config_manager=mock_config)
    
    # Mock internal services
    orch.llm_manager = MagicMock()
    orch.prompt_composer = MagicMock()
    orch.i18n = MagicMock()
    orch.location_service = MagicMock()
    orch.workspace_service = MagicMock()
    orch.scratchpad_service = MagicMock()
    
    return orch

def test_decision_logic_failed_always_notifies(orchestrator):
    session = MagicMock()
    session.task_registry = {"task_123": "Web Researcher"}
    
    events = [
        {
            "event_type": "FAILED",
            "task_id": "task_123",
            "failure_summary": "Connection timeout",
            "attention_level": "low"
        }
    ]
    
    notifications = orchestrator._decide_on_worker_events(session, events)
    assert len(notifications) == 1
    assert "Web Researcher" in notifications[0]
    assert "failed" in notifications[0].lower()
    assert "Connection timeout" in notifications[0]

def test_decision_logic_waiting_input_always_notifies(orchestrator):
    session = MagicMock()
    session.task_registry = {"task_456": "Code Auditor"}
    
    events = [
        {
            "event_type": "WAITING_INPUT",
            "task_id": "task_456",
            "summary": "Need API key",
            "attention_level": "low"
        }
    ]
    
    notifications = orchestrator._decide_on_worker_events(session, events)
    assert len(notifications) == 1
    assert "Code Auditor" in notifications[0]
    assert "waiting for your input" in notifications[0].lower()

def test_decision_logic_progress_low_is_silent(orchestrator):
    session = MagicMock()
    session.task_registry = {"task_789": "Data Processor"}
    
    events = [
        {
            "event_type": "PROGRESS",
            "task_id": "task_789",
            "summary": "Scanning files...",
            "attention_level": "low"
        }
    ]
    
    notifications = orchestrator._decide_on_worker_events(session, events)
    assert len(notifications) == 0

def test_decision_logic_high_attention_notifies(orchestrator):
    session = MagicMock()
    session.task_registry = {"task_abc": "Security Scanner"}
    
    events = [
        {
            "event_type": "PROGRESS",
            "task_id": "task_abc",
            "summary": "CRITICAL vulnerability found",
            "attention_level": "high"
        }
    ]
    
    notifications = orchestrator._decide_on_worker_events(session, events)
    assert len(notifications) == 1
    assert "Security Scanner" in notifications[0]
    assert "CRITICAL vulnerability found" in notifications[0]

def test_decision_logic_completed_low_is_silent(orchestrator):
    session = MagicMock()
    session.task_registry = {"task_xyz": "File Cleaner"}
    
    events = [
        {
            "event_type": "COMPLETED",
            "task_id": "task_xyz",
            "summary": "Cleanup done",
            "attention_level": "low"
        }
    ]
    
    notifications = orchestrator._decide_on_worker_events(session, events)
    assert len(notifications) == 0

def test_decision_logic_completed_medium_notifies(orchestrator):
    session = MagicMock()
    session.task_registry = {"task_xyz": "Deep Researcher"}
    
    events = [
        {
            "event_type": "COMPLETED",
            "task_id": "task_xyz",
            "summary": "Final report ready",
            "attention_level": "medium"
        }
    ]
    
    notifications = orchestrator._decide_on_worker_events(session, events)
    assert len(notifications) == 1
    assert "Deep Researcher" in notifications[0]
    assert "completed its task" in notifications[0].lower()
