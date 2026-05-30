import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.core.observation import ActionObservation
from src.services.llm.prompt_composer import PromptComposer
from src.utils.toon_codec import encode_state_summary


def _compose_last_mile_prompt(observation_text: str, state_update: dict) -> str:
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
        toon_state=json.dumps(encode_state_summary(state_update), ensure_ascii=False),
        toon_deltas=[],
        user_input="liste as imagens reais da pasta Downloads",
        project_path="/tmp/project",
        workspace_path="/tmp/workspace",
        venv_python="/tmp/env/bin/python",
        venv_pip="/tmp/env/bin/pip",
        browser_pages=[],
        session_summary=observation_text,
        scratchpad="",
        attachments=[],
        capabilities_summary="- `system.control.consult_tools`: ...\n- `system.control.fs.list`: ...",
        capability_scope="principal-filtered",
    )


def test_last_mile_prompt_keeps_only_real_items_from_evidence_preview():
    results = [
        {"name": "ba9b1e58-3b5d-4e0c-9dfb-97bd1d8c6026.jpeg"},
        {"name": "maskable_icon (4).png"},
        {"name": "download (2).jpeg"},
        {"name": "WhatsApp Image 2026-05-06 at 13.35.32.jpeg"},
        {"name": "7958c693-1c02-42bb-9a35-9cd74c47afef.png"},
        {"name": "1d11079b-fdca-4e66-a9df-cede974b3f30.png"},
        {"name": "4956333358862502881 (3).png"},
        {"name": "snapshot-saturn.png"},
        {"name": "images.jpeg"},
        {"name": "images (1).jpeg"},
        {"name": "maskable_icon (2).png"},
        {"name": "4956333358862502881.jpg"},
        {"name": "maskable_icon (1).png"},
        {"name": "c258eb81-dee7-4117-ba15-0cdd0043c127.png"},
        {"name": "5785af62-a0fc-4a5a-bd45-b076c6bf7ef1.png"},
    ]
    obs = ActionObservation.from_execution(
        action_name="system.control.fs.list",
        capability="system_control",
        status="success",
        reason="success",
        structured_result={
            "path": "/home/lucas/Downloads",
            "count": len(results),
            "results": results,
        },
        raw_result_preview="{...large...}",
        work_id="work-last-mile",
    )

    assert obs.evidence_total == 15
    assert obs.evidence_shown == 12
    assert obs.evidence_truncated is True
    assert obs.freshness_note == "fresh_current_turn"
    assert obs.observed_work_id == "work-last-mile"
    assert obs.source_action == "system.control.fs.list"
    assert obs.evidence_items[:3] == [
        "ba9b1e58-3b5d-4e0c-9dfb-97bd1d8c6026.jpeg",
        "maskable_icon (4).png",
        "download (2).jpeg",
    ]

    observation_text = (
        "RESULT OF ACTION system.control.fs.list [status=success; reason=success]: {...large...}\n"
        f"EVIDENCE PREVIEW: {obs.to_evidence_summary()}\n"
        "GROUNDING RULE: cite only items present in the evidence preview; if it is truncated, say so explicitly."
    )
    prompt = _compose_last_mile_prompt(observation_text, obs.to_state_summary_update())

    assert "[ATLAS OPERATING MODEL]" in prompt
    assert "EVIDENCE PREVIEW:" in prompt
    assert "GROUNDING RULE: cite only items present in the evidence preview" in prompt
    assert "truncated=yes" in prompt
    assert "ba9b1e58-3b5d-4e0c-9dfb-97bd1d8c6026.jpeg" in prompt
    assert "maskable_icon (4).png" in prompt
    assert "download (2).jpeg" in prompt
    assert "wallpaper_01.png" not in prompt
    assert "projeto_diagrama.jpg" not in prompt
    assert "screenshot_2026_05_30.png" not in prompt
    assert "backup_icon.svg" not in prompt
    assert "foto_perfil_v2.jpg" not in prompt
