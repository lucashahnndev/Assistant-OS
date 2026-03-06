from core.orchestrator import AgentOrchestrator


def test_detects_assistive_screen_request_pt():
    text = "atlas, me mostra na minha tela onde fica o icone de rede"
    assert AgentOrchestrator._looks_like_assistive_screen_request(text) is True


def test_detects_assistive_screen_request_en():
    text = "show on screen where the network icon is"
    assert AgentOrchestrator._looks_like_assistive_screen_request(text) is True


def test_does_not_flag_generic_non_assistive_request():
    text = "qual o clima em Sao Paulo hoje?"
    assert AgentOrchestrator._looks_like_assistive_screen_request(text) is False
