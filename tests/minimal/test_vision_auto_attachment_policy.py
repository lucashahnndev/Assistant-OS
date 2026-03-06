from core.orchestrator import AgentOrchestrator


def test_auto_attachment_disabled_for_vision_actions():
    assert AgentOrchestrator._should_auto_attach_action_output("vision.search_screen") is False
    assert AgentOrchestrator._should_auto_attach_action_output("vision.locate_screen") is False
    assert AgentOrchestrator._should_auto_attach_action_output("vision.analyze") is False


def test_auto_attachment_enabled_for_non_vision_actions():
    assert AgentOrchestrator._should_auto_attach_action_output("overlay.assist.highlight_target") is True
    assert AgentOrchestrator._should_auto_attach_action_output("reply") is True
    assert AgentOrchestrator._should_auto_attach_action_output(None) is True
