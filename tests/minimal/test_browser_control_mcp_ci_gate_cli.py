import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

import scripts.browser_control_mcp_ci_gate as gate


def _run_cli(args):
    cmd = [
        str(ROOT / "env" / "bin" / "python"),
        str(ROOT / "scripts" / "browser_control_mcp_ci_gate.py"),
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=False)


def _smoke_payload(*, transport_mode_effective: str = "mcp", mcp_calls_total: int = 2, issues=None):
    return {
        "ok": True,
        "stages": {
            "run": {"ok": True},
            "inspect": {"ok": True},
            "sync_registry": {
                "ok": True,
                "runtime_backend": "playwright",
                "transport_mode_effective": transport_mode_effective,
                "mcp_calls_total": mcp_calls_total,
            },
            "health": {"ok": True, "health": {"issues": list(issues or [])}},
        },
    }


def test_evaluate_gate_passes_with_good_smoke():
    passed, checks = gate.evaluate_gate(
        _smoke_payload(),
        allow_local_fallback=False,
        min_mcp_calls=1,
        allowed_health_issues=[],
    )
    assert passed is True
    assert all(c["passed"] for c in checks)


def test_evaluate_gate_fails_on_local_fallback_when_not_allowed():
    passed, checks = gate.evaluate_gate(
        _smoke_payload(transport_mode_effective="local"),
        allow_local_fallback=False,
        min_mcp_calls=1,
        allowed_health_issues=[],
    )
    assert passed is False
    failed = [c["name"] for c in checks if not c["passed"]]
    assert "transport_effective_mcp" in failed


def test_gate_cli_uses_smoke_report_file_and_fails_when_threshold_not_met():
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "smoke.json"
        report.write_text(json.dumps(_smoke_payload(mcp_calls_total=0)), encoding="utf-8")
        out = _run_cli(["--smoke-report-file", str(report), "--min-mcp-calls", "1"])
        assert out.returncode == 2
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is False
        assert payload["error_code"] == "CI_GATE_FAILED"


def test_gate_cli_allows_health_issue_when_whitelisted():
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "smoke.json"
        report.write_text(json.dumps(_smoke_payload(issues=["mcp_fell_back_to_local"])), encoding="utf-8")
        out = _run_cli(
            [
                "--smoke-report-file",
                str(report),
                "--allow-local-fallback",
                "--allow-health-issue",
                "mcp_fell_back_to_local",
            ]
        )
        assert out.returncode == 0
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is True


def test_gate_cli_writes_markdown_report_file():
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "smoke.json"
        md = Path(tmp) / "out" / "gate.md"
        report.write_text(json.dumps(_smoke_payload()), encoding="utf-8")
        out = _run_cli(["--smoke-report-file", str(report), "--markdown-report-file", str(md)])
        assert out.returncode == 0
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is True
        assert payload["markdown_report_file"] == str(md)
        text = md.read_text(encoding="utf-8")
        assert "# Browser Control MCP CI Gate Report" in text
        assert "| `smoke_ok` | `PASS` |" in text


def test_gate_cli_markdown_report_marks_failed_checks():
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "smoke.json"
        md = Path(tmp) / "gate.md"
        report.write_text(json.dumps(_smoke_payload(mcp_calls_total=0)), encoding="utf-8")
        out = _run_cli(["--smoke-report-file", str(report), "--min-mcp-calls", "1", "--markdown-report-file", str(md)])
        assert out.returncode == 2
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is False
        text = md.read_text(encoding="utf-8")
        assert "| `mcp_calls_threshold` | `FAIL` |" in text


def test_gate_cli_writes_json_report_file():
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "smoke.json"
        out_json = Path(tmp) / "out" / "gate.json"
        report.write_text(json.dumps(_smoke_payload()), encoding="utf-8")
        out = _run_cli(["--smoke-report-file", str(report), "--json-report-file", str(out_json)])
        assert out.returncode == 0
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is True
        assert payload["json_report_file"] == str(out_json)
        stored = json.loads(out_json.read_text(encoding="utf-8"))
        assert stored["ok"] is True
        assert stored["mode"] == "gate"
        assert isinstance(stored["checks"], list)


def test_gate_cli_writes_both_markdown_and_json_reports():
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "smoke.json"
        out_md = Path(tmp) / "out" / "gate.md"
        out_json = Path(tmp) / "out" / "gate.json"
        report.write_text(json.dumps(_smoke_payload()), encoding="utf-8")
        out = _run_cli(
            [
                "--smoke-report-file",
                str(report),
                "--markdown-report-file",
                str(out_md),
                "--json-report-file",
                str(out_json),
            ]
        )
        assert out.returncode == 0
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is True
        assert out_md.exists() is True
        assert out_json.exists() is True


def test_gate_cli_summary_only_returns_compact_payload_success():
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "smoke.json"
        report.write_text(json.dumps(_smoke_payload()), encoding="utf-8")
        out = _run_cli(["--smoke-report-file", str(report), "--summary-only"])
        assert out.returncode == 0
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is True
        assert payload["mode"] == "gate"
        assert payload["failed_checks"] == []
        assert "smoke" not in payload
        assert "checks" not in payload


def test_gate_cli_summary_only_returns_failed_checks_on_error():
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "smoke.json"
        report.write_text(json.dumps(_smoke_payload(mcp_calls_total=0)), encoding="utf-8")
        out = _run_cli(["--smoke-report-file", str(report), "--min-mcp-calls", "1", "--summary-only"])
        assert out.returncode == 2
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is False
        assert "mcp_calls_threshold" in payload["failed_checks"]
        assert "smoke" not in payload
