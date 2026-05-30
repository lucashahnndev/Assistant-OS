import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for candidate in (ROOT, ROOT / "src"):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from core.orchestrator import AgentOrchestrator
from core.resolution.action_plan import ActionPlan
from core.session import Session
from services.llm.prompt_composer import PromptComposer
from src.utils.toon_codec import encode_state_summary


class _CapabilityRegistryStub:
    def get_action_metadata(self, action_id: str):
        if action_id == "system.control.fs.list":
            return {
                "capability_id": "system_control",
                "capability": "system_control",
                "namespace": "system.control",
            }
        return {}


def _compose_next_prompt(session: Session) -> str:
    composer = PromptComposer()
    return composer.compose(
        agent_name="Atlas",
        personality="You are practical.",
        specialist_prompt="",
        presentation_directive="[PRESENTATION DIRECTIVE]\n- concise",
        instruction_pack="",
        sys_info={"date": "2026-03-06", "time": "01:00:00", "os": "Linux", "user": "lucas"},
        location="Unknown",
        channel=session.context.get("channel", "web"),
        user_name=session.context.get("user_name", "admin"),
        user_language=session.context.get("user_language", "pt-BR"),
        toon_state=json.dumps(encode_state_summary(session.state_summary), ensure_ascii=False),
        toon_deltas=[],
        user_input="liste as imagens reais da pasta Downloads",
        initial_user_request="liste as imagens reais da pasta Downloads",
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
        relevant_memory=[],
        context_bundle=None,
        prompt_profile="operational",
    )


def test_orchestrator_grounding_flow_keeps_real_evidence_in_next_prompt():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.capability_registry = _CapabilityRegistryStub()

    session = Session("session-grounding", source="web")
    session.turn_id = 7
    session.state_summary["turn_id"] = 7
    session.context.update({"channel": "web", "user_name": "admin", "user_language": "pt-BR"})

    plan = ActionPlan(
        action_id="system.control.fs.list",
        args={"path": "/home/lucas/Downloads"},
        confidence=0.92,
        source="llm",
        thought="Listar imagens da pasta Downloads",
    )
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
    structured_result = {
        "path": "/home/lucas/Downloads",
        "count": 79,
        "results": results,
    }

    action_observation = orchestrator._build_action_observation(
        session=session,
        work_id="work-grounding",
        plan=plan,
        result_status="success",
        result_reason="success",
        structured_result=structured_result,
        raw_result=json.dumps(structured_result, ensure_ascii=False),
        truncated_result=json.dumps(structured_result, ensure_ascii=False)[:120],
        summary=None,
        extracted_sources=[],
        last_generated_attachment_paths=[],
    )

    evidence_summary = action_observation.to_evidence_summary()
    prompt_summary = action_observation.to_prompt_summary()
    observation_text = (
        "RESULT OF ACTION system.control.fs.list [status=success; reason=success]: ...\n"
        f"EVIDENCE PREVIEW: {evidence_summary}\n"
        "GROUNDING RULE: cite only items present in the evidence preview; if it is truncated, say so explicitly."
    )

    session.context["last_action_observation"] = action_observation.to_dict()
    session.state_summary.update(action_observation.to_state_summary_update())
    session.add_message(
        "system",
        observation_text,
        msg_type="reasoning",
        summary=action_observation.to_prompt_summary(),
        work_id="work-grounding",
    )
    session.summary = observation_text

    prompt = _compose_next_prompt(session)

    assert session.context["last_action_observation"]["evidence_total"] == 79
    assert session.context["last_action_observation"]["evidence_shown"] == 12
    assert session.state_summary["last_observation_evidence_truncated"] is True
    assert session.state_summary["last_observation_evidence_count"] == 79
    assert session.state_summary["last_observation_evidence_shown"] == 12
    assert session.state_summary["last_observation_freshness"] == "fresh_current_turn"
    assert "observed_turn=" in prompt_summary
    assert "work=work-grounding" in prompt_summary
    assert "freshness=fresh_current_turn" in prompt_summary

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
    assert "copy and paste" not in prompt.lower()
    assert "do not invent files, IDs, paths, or results." in prompt
