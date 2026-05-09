import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.services.llm.prompt_composer import PromptComposer


def _compose(response_persona: str) -> str:
    pc = PromptComposer()
    return pc.compose(
        agent_name="Atlas",
        personality="You are formal and always say sir.",
        response_persona=response_persona,
        specialist_prompt="",
        presentation_directive="[PRESENTATION DIRECTIVE]\n- concise",
        instruction_pack="",
        sys_info={"date": "2026-03-06", "time": "01:00:00", "os": "Linux", "user": "lucas"},
        location="Unknown",
        channel="web",
        user_name="admin",
        user_language="pt-BR",
        toon_state="{}",
        toon_deltas=[],
        user_input="oi",
        project_path="/tmp/project",
        workspace_path="/tmp/workspace",
        venv_python="/tmp/env/bin/python",
        venv_pip="/tmp/env/bin/pip",
        browser_pages=[],
        session_summary="",
        scratchpad="",
        attachments=[],
        capabilities_summary="- `reply`: ...",
        capability_scope="principal-filtered",
    )


def test_response_persona_section_is_scoped_to_response_text():
    prompt = _compose("Use a formal butler tone and address the user as sir.")
    assert "[RESPONSE PERSONA]" not in prompt
    assert "response_text" not in prompt.lower()


def test_response_persona_section_absent_when_empty():
    prompt = _compose("")
    assert "[RESPONSE PERSONA]" not in prompt
