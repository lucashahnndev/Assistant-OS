import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for candidate in (ROOT, ROOT / "src"):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from core.observation import ActionObservation
from core.session import Session
from services.llm.prompt_composer import PromptComposer
from utils.toon_codec import encode_state_summary


def _compose_prompt(session: Session, user_input: str) -> str:
    composer = PromptComposer()
    return composer.compose(
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
        toon_state=json.dumps(encode_state_summary(session.state_summary), ensure_ascii=False),
        toon_deltas=[],
        user_input=user_input,
        initial_user_request=user_input,
        project_path="/tmp/project",
        workspace_path="/tmp/workspace",
        venv_python="/tmp/env/bin/python",
        venv_pip="/tmp/env/bin/pip",
        browser_pages=[],
        session_summary=session.summary,
        scratchpad="",
        attachments=[],
        capabilities_summary="- `system.control.consult_tools`: ...\n- `system.control.fs.list`: ...",
        capability_scope="principal-filtered",
    )


def test_stale_observation_is_marked_and_prompt_warns_against_memory_grounding():
    session = Session("session-freshness", source="web")
    stale_obs = ActionObservation.from_execution(
        action_name="system.control.fs.list",
        capability="system_control",
        status="success",
        reason="success",
        structured_result={
            "path": "/home/lucas/Downloads",
            "count": 3,
            "results": [
                {"name": "a.png"},
                {"name": "b.jpg"},
                {"name": "c.jpeg"},
            ],
        },
        raw_result_preview="{...}",
        work_id="work-old",
        turn_id=4,
        source_args={"path": "/home/lucas/Downloads"},
    )
    session.state_summary.update(stale_obs.to_state_summary_update())
    assert session.state_summary["last_observation_freshness"] == "fresh_current_turn"

    session.add_message("user", "Liste novamente as imagens reais da pasta Downloads", work_id="work-new")
    assert session.state_summary["last_observation_freshness"] == "stale"
    assert session.state_summary["last_observation_stale_at_turn_id"] == session.turn_id

    prompt = _compose_prompt(session, "Liste novamente as imagens reais da pasta Downloads")

    assert "Do not answer current factual or enumerable requests from memory" in prompt
    assert '"lof": "stale"' in prompt
    assert '"lot":4' in prompt or '"lot": 4' in prompt
    assert '"low": "work-old"' in prompt
    assert '"loa": "system.control.fs.list"' in prompt
    assert '/home/lucas/Downloads' in prompt
