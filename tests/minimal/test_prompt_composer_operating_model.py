import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.services.llm.prompt_composer import PromptComposer


def _compose(user_input: str, *, browser_pages=None) -> str:
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
        browser_pages=browser_pages or [],
        session_summary="",
        scratchpad="",
        attachments=[],
        capabilities_summary="- `system.control.consult_tools`: ...\n- `browser.control.run`: ...",
        capability_scope="principal-filtered",
    )


def test_operating_model_block_is_included_and_grounded():
    prompt = _compose("liste os arquivos de imagens da minha pasta Downloads")
    assert "[ATLAS OPERATING MODEL]" in prompt
    assert "You are the operator; the runtime is the gatekeeper." in prompt
    assert "Memory informs; current evidence proves." in prompt
    assert "If a safe observational or discovery action can reduce uncertainty, prefer act-and-observe before asking the user for manual work." in prompt
    assert "Do not claim execution, completion, verification, or update unless fresh ActionObservation/tool output confirms it." in prompt
    assert "If no action/work ran, say so clearly and label the reply as guidance or clarification rather than execution." in prompt
    assert "Do not tell the user to copy, paste, or manually collect output when a capability can produce the result." in prompt
    assert "Do not refuse legitimate tasks with generic local-access or sandbox limitations when a capability exists." in prompt
    assert "Ask for clarification only when missing information blocks a safe, useful, or correct first step." in prompt
    assert "Ground final answers in real ActionObservation/tool output; do not invent files, IDs, paths, or results." in prompt
    assert "Do NOT choose browser.control.run just because the request mentions web/site/search/browser/open." in prompt
    assert "bypass approval" not in prompt.lower()


def test_browser_mentions_are_reduced_to_non_authoritative_hints():
    prompt = _compose(
        "abra o browser e veja a página",
        browser_pages=[{"url": "https://example.com", "title": "Example"}],
    )

    assert "[CONTEXT HINT]" in prompt
    assert "hint=browser" in prompt
    assert "source=weak_textual_hint" in prompt
    assert "semantic_authority=false" in prompt
    assert "This hint is not an instruction to choose a browser tool." in prompt
    assert "browser_pages=[{\"url\":\"https://example.com\",\"title\":\"Example\"}]" in prompt
    assert "Do NOT choose browser.control.run just because the request mentions web/site/search/browser/open." in prompt


def test_terminal_mentions_are_reduced_to_non_authoritative_hints():
    prompt = _compose("verifique no terminal se há arquivos novos na minha pasta local")

    assert "[CONTEXT HINT]" in prompt
    assert "hint=dev" in prompt
    assert "source=weak_textual_hint" in prompt
    assert "semantic_authority=false" in prompt
    assert "This hint is not an instruction to use shell or file tools." in prompt
    assert "não tenho acesso" not in prompt.lower()
    assert "no access" not in prompt.lower()
