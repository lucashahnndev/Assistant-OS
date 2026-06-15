import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.core.observation import ActionObservation
from src.utils.toon_codec import encode_state_summary


def test_action_observation_creates_structured_envelope_and_prompt_summary():
    obs = ActionObservation.from_execution(
        action_name="browser.control.run",
        capability="browser",
        status="failure",
        reason="BROKEN_LINK",
        result_summary="Broken media link detected",
        structured_result={
            "error_code": "BROKEN_LINK",
            "validation_failures": ["url"],
            "retryable": True,
            "freshness": {
                "source": "cache",
                "resolved_at": "2026-06-11T12:00:00Z",
                "stale": True,
                "ttl_seconds": 120,
            },
        },
        raw_result_preview='{"status":"failure","error_code":"BROKEN_LINK"}',
        state_changes={"cursor": "1/4"},
        artifacts={"attachments": ["/tmp/example.png"]},
        raw_result_ref={"kind": "none", "available": False, "redacted": False},
        raw_result_redaction={
            "applied": True,
            "removed_fields": ["text", "message", "reply"],
            "reason": "prevent_prompt_contamination",
            "preview_sanitized": True,
        },
        repair_context={"hint": "search another candidate"},
        requires_replan=True,
        work_id="work-123",
        turn_id=7,
    )

    payload = obs.to_dict()
    assert payload["action_name"] == "browser.control.run"
    assert payload["capability"] == "browser"
    assert payload["status"] == "failure"
    assert payload["success"] is False
    assert payload["requires_replan"] is True
    assert payload["repair_context"]["error_code"] == "BROKEN_LINK"
    assert payload["state_changes"]["cursor"] == "1/4"
    assert payload["raw_result_ref"]["available"] is False
    assert payload["raw_result_redaction"]["applied"] is True
    assert payload["raw_result_redaction"]["removed_fields"] == ["text", "message", "reply"]
    assert payload["freshness"]["source"] == "cache"
    assert payload["freshness"]["stale"] is True
    assert payload["freshness"]["ttl_seconds"] == 120
    assert payload["freshness_note"] == "fresh_current_turn"

    prompt_summary = obs.to_prompt_summary()
    assert "action=browser.control.run" in prompt_summary
    assert "status=failure" in prompt_summary
    assert "replan=yes" in prompt_summary
    assert "freshness_detail=" in prompt_summary
    assert "raw_result_ref=" in prompt_summary
    assert "raw_result_redaction=" in prompt_summary

    state_update = obs.to_state_summary_update()
    assert state_update["last_observation_freshness_source"] == "cache"
    assert state_update["last_observation_freshness_stale"] is True
    encoded = encode_state_summary(
        {
            "goal": "Task",
            "cursor": "1/4",
            "last_outcome": "ok",
            "last_error": "none",
            **state_update,
        }
    )
    assert encoded["lo"].startswith("action=browser.control.run")
    assert encoded["ls"] == "failure"
    assert encoded["lr"] == "BROKEN_LINK"


def test_action_observation_extracts_faithful_evidence_preview_from_enumerable_results():
    obs = ActionObservation.from_execution(
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
        raw_result_preview="{\"count\":3,\"results\":[{\"name\":\"a.png\"},{\"name\":\"b.jpg\"},{\"name\":\"c.jpeg\"}]}",
        work_id="work-xyz",
    )

    assert obs.evidence_items == ["a.png", "b.jpg", "c.jpeg"]
    assert obs.evidence_total == 3
    assert obs.evidence_shown == 3
    assert obs.evidence_truncated is False
    assert obs.evidence_source_path == "/home/lucas/Downloads"
    assert obs.evidence_selection_rule == "structured_result.results[]->name"
    assert obs.to_dict()["evidence_items"] == ["a.png", "b.jpg", "c.jpeg"]

    prompt_summary = obs.to_prompt_summary()
    assert "action=system.control.fs.list" in prompt_summary
    assert "evidence=" in prompt_summary
    assert "a.png" in prompt_summary
    assert "b.jpg" in prompt_summary
    assert "c.jpeg" in prompt_summary
    assert "truncated=no" in prompt_summary

    state_update = obs.to_state_summary_update()
    encoded = encode_state_summary(
        {
            "goal": "Task",
            "cursor": "1/4",
            "last_outcome": "ok",
            "last_error": "none",
            **state_update,
        }
    )
    assert "a.png" in encoded["le"]
    assert encoded["lc"] == 3
    assert encoded["lsn"] == 3
    assert encoded["lt"] is False


def test_action_observation_marks_truncation_and_limits_evidence_preview():
    results = [{"name": f"file_{index}.png"} for index in range(1, 26)]
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
        work_id="work-xyz",
    )

    assert obs.evidence_total == 25
    assert obs.evidence_shown == 12
    assert obs.evidence_truncated is True
    assert len(obs.evidence_items) == 12
    assert obs.evidence_items[0] == "file_1.png"
    assert obs.evidence_items[-1] == "file_12.png"
    assert "file_13.png" not in obs.evidence_items
    assert obs.to_dict()["evidence_truncated"] is True
    assert obs.evidence_warning.startswith("truncated; showing first 12 of 25")

    prompt_summary = obs.to_prompt_summary()
    assert "truncated=yes" in prompt_summary
    assert "file_1.png" in prompt_summary
    assert "file_13.png" not in prompt_summary

    state_update = obs.to_state_summary_update()
    assert state_update["last_observation_evidence_truncated"] is True
    encoded = encode_state_summary(
        {
            "goal": "Task",
            "cursor": "1/4",
            "last_outcome": "ok",
            "last_error": "none",
            **state_update,
        }
    )
    assert encoded["lt"] is True
    assert encoded["lc"] == 25
    assert encoded["lsn"] == 12
