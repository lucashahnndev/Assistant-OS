import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.services.llm.prompt_composer import PromptComposer


def _compose(user_input: str) -> str:
    pc = PromptComposer()
    return pc.compose(
        agent_name="Atlas",
        personality="You are practical.",
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
        user_input=user_input,
        project_path="/tmp/project",
        workspace_path="/tmp/workspace",
        venv_python="/tmp/env/bin/python",
        venv_pip="/tmp/env/bin/pip",
        browser_pages=[],
        session_summary="",
        scratchpad="",
        attachments=[],
        capabilities_summary="- `overlay.assist.highlight_target`: ...\n- `vision.search_screen`: ...",
        capability_scope="principal-filtered",
    )


def test_assistive_mode_directive_is_included_for_screen_mark_requests():
    prompt = _compose("atlas, me mostra na minha tela onde está o ícone de rede")
    assert "[ASSISTIVE MODE DIRECTIVE]" in prompt
    assert "Prefer `overlay.assist.highlight_target` for marking" in prompt


def test_assistive_mode_directive_not_included_for_generic_chat():
    prompt = _compose("qual a capital da frança?")
    assert "[ASSISTIVE MODE DIRECTIVE]" not in prompt
