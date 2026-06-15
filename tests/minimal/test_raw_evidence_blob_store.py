import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from core.observation import ActionObservation
from core.orchestrator import AgentOrchestrator
from core.session_event_pipeline import build_session_snapshot


def test_raw_evidence_blob_store_persists_raw_result_and_references_it(tmp_path):
    raw_result = {
        "ok": True,
        "status": "success",
        "text": "TOP SECRET RAW TEXT",
        "message": "should stay out of prompt",
        "reply": "assistant-like content",
        "items": [{"name": "alpha.txt"}],
    }

    ref = AgentOrchestrator._persist_raw_result_blob(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-raw",
        work_id="work-1",
        turn_id=8,
        action_name="files.read",
        capability="fs_control",
        raw_result=raw_result,
    )

    assert ref["kind"] == "session_raw_result"
    assert ref["available"] is True
    assert ref["redacted"] is False
    assert ref["stored_truncated"] is False
    assert ref["id"].startswith("raw_")
    assert ref["retention"]["policy"] == "session_debug_default"
    assert ref["retention"]["ttl_seconds"] >= 60
    assert ref["access"]["prompt_visible"] is False

    session_dir = Path(tmp_path, "sessions", "sess-raw")
    index_path = session_dir / "raw_evidence.index.json"
    assert index_path.exists()
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    stored = index_data["items"][ref["id"]]
    blob_path = Path(stored["path"])
    assert blob_path.exists()
    blob = json.loads(blob_path.read_text(encoding="utf-8"))
    assert blob["raw_result_id"] == ref["id"]
    assert blob["stored_truncated"] is False
    assert "TOP SECRET RAW TEXT" in blob["raw_text"]
    assert blob["retention"]["policy"] == "session_debug_default"
    assert blob["access"]["scope"] == "internal_audit"

    obs = ActionObservation.from_execution(
        action_name="files.read",
        capability="fs_control",
        status="success",
        reason="success",
        structured_result={"ok": True, "status": "success", "freshness": {"source": "live"}},
        raw_result_preview='{"ok":true,"status":"success"}',
        raw_result_ref=ref,
        raw_result_redaction={
            "applied": True,
            "removed_fields": ["text", "message", "reply"],
            "reason": "prevent_prompt_contamination",
            "preview_sanitized": True,
        },
    )

    prompt_summary = obs.to_prompt_summary()
    assert "raw_result_ref=" in prompt_summary
    assert "raw_result_redaction=" in prompt_summary
    assert "TOP SECRET RAW TEXT" not in prompt_summary
    assert obs.to_dict()["raw_result_ref"]["available"] is True

    snapshot = build_session_snapshot("sess-raw", base_data_dir=str(tmp_path))
    assert snapshot["paths"]["raw_evidence_dir"] == str(session_dir / "raw_evidence")
    assert snapshot["indices"]["raw_evidence"]["items"][ref["id"]]["available"] is True


def test_raw_evidence_gc_removes_expired_blob_and_keeps_index_honest(tmp_path):
    ref = AgentOrchestrator._persist_raw_result_blob(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-gc",
        work_id="work-gc",
        turn_id=11,
        action_name="files.read",
        capability="fs_control",
        raw_result={"ok": True, "text": "hello"},
        ttl_seconds=1,
    )

    session_dir = Path(tmp_path, "sessions", "sess-gc")
    blob_path = session_dir / "raw_evidence" / f"{ref['id']}.json"
    assert blob_path.exists()

    gc_report = AgentOrchestrator.gc_raw_evidence_store(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-gc",
        now_ts=int(time.time()) + 10,
    )

    assert gc_report["expired"] >= 1
    assert not blob_path.exists()

    index_path = session_dir / "raw_evidence.index.json"
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    assert ref["id"] in index_data["items"]
    assert index_data["items"][ref["id"]]["available"] is False
    assert index_data["items"][ref["id"]]["expired"] is True

    resolved = AgentOrchestrator.resolve_raw_evidence_ref(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-gc",
        raw_result_ref=ref,
    )
    assert resolved["available"] is False
    assert resolved["reason"] == "expired"


def test_raw_evidence_gc_preserves_pinned_blob(tmp_path):
    ref = AgentOrchestrator._persist_raw_result_blob(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-pin",
        work_id="work-pin",
        turn_id=12,
        action_name="files.read",
        capability="fs_control",
        raw_result={"ok": True, "text": "pinned"},
        ttl_seconds=1,
        pinned=True,
    )

    session_dir = Path(tmp_path, "sessions", "sess-pin")
    blob_path = session_dir / "raw_evidence" / f"{ref['id']}.json"
    gc_report = AgentOrchestrator.gc_raw_evidence_store(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-pin",
        now_ts=int(time.time()) + 10,
    )

    assert gc_report["pinned"] >= 1
    assert blob_path.exists()

    index_path = session_dir / "raw_evidence.index.json"
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    record = index_data["items"][ref["id"]]
    assert record["retention"]["pinned"] is True
    assert record["available"] is True


def test_raw_evidence_gc_enforces_max_items_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("RAW_EVIDENCE_MAX_ITEMS", "1")

    first = AgentOrchestrator._persist_raw_result_blob(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-limit",
        work_id="work-limit-1",
        turn_id=14,
        action_name="files.read",
        capability="fs_control",
        raw_result={"ok": True, "text": "first"},
    )
    second = AgentOrchestrator._persist_raw_result_blob(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-limit",
        work_id="work-limit-2",
        turn_id=15,
        action_name="files.read",
        capability="fs_control",
        raw_result={"ok": True, "text": "second"},
    )

    session_dir = Path(tmp_path, "sessions", "sess-limit")
    index_data = json.loads((session_dir / "raw_evidence.index.json").read_text(encoding="utf-8"))
    assert second["id"] in index_data["items"]
    assert first["id"] not in index_data["items"]
    assert not (session_dir / "raw_evidence" / f"{first['id']}.json").exists()
    assert (session_dir / "raw_evidence" / f"{second['id']}.json").exists()


def test_raw_evidence_ref_becomes_unavailable_when_blob_is_deleted(tmp_path):
    ref = AgentOrchestrator._persist_raw_result_blob(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-missing",
        work_id="work-missing",
        turn_id=13,
        action_name="files.read",
        capability="fs_control",
        raw_result={"ok": True, "text": "gone"},
    )

    session_dir = Path(tmp_path, "sessions", "sess-missing")
    blob_path = session_dir / "raw_evidence" / f"{ref['id']}.json"
    blob_path.unlink()

    resolved = AgentOrchestrator.resolve_raw_evidence_ref(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-missing",
        raw_result_ref=ref,
    )

    assert resolved["available"] is False
    assert resolved["reason"] == "missing_blob"
    assert resolved["access"]["user_visible"] is False
    assert resolved["access"]["prompt_visible"] is False


def test_raw_evidence_blob_store_marks_truncation_when_blob_is_large(tmp_path):
    ref = AgentOrchestrator._persist_raw_result_blob(
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-trunc",
        work_id="work-2",
        turn_id=9,
        action_name="system.control.fs.read",
        capability="system_control",
        raw_result="x" * 100,
        max_chars=32,
    )

    assert ref["available"] is True
    assert ref["stored_truncated"] is True

    blob_path = Path(tmp_path, "sessions", "sess-trunc", "raw_evidence", f"{ref['id']}.json")
    blob = json.loads(blob_path.read_text(encoding="utf-8"))
    assert blob["stored_truncated"] is True
    assert len(blob["raw_text"]) == 32


def test_raw_evidence_blob_store_failure_is_honest_and_non_fatal(monkeypatch, tmp_path):
    session = SimpleNamespace(context={}, state_summary={})

    def _raise(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(AgentOrchestrator, "_atomic_write_json", staticmethod(_raise))

    ref = AgentOrchestrator._safe_persist_raw_result_blob(
        session=session,
        sessions_dir=str(tmp_path / "sessions"),
        session_id="sess-fail",
        work_id="work-3",
        turn_id=10,
        action_name="browser.control.run",
        capability="browser_control",
        raw_result={"ok": True, "text": "secret"},
    )

    assert ref["available"] is False
    assert ref["reason"] == "store_failed"
    assert session.context["last_raw_result_store_error"] == "disk full"
    assert session.state_summary["last_raw_result_store_error"] == "disk full"
