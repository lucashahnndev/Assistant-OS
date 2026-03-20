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

from scripts.browser_control_mcp_preflight import analyze_browser_control_mcp_readiness


def _run_cli(args):
    cmd = [
        str(ROOT / "env" / "bin" / "python"),
        str(ROOT / "scripts" / "browser_control_mcp_preflight.py"),
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=False)


def test_analyze_readiness_detects_required_mcp_fields():
    ready_cfg = {
        "runtime_backend": "playwright",
        "playwright_transport_mode": "mcp",
        "playwright_mcp_endpoint": "http://127.0.0.1:8787",
        "playwright_mcp_fallback_to_local": False,
    }
    ready = analyze_browser_control_mcp_readiness(ready_cfg)
    assert ready["ready"] is True
    assert ready["issues"] == []
    assert ready["warnings"] == []

    not_ready = analyze_browser_control_mcp_readiness({"runtime_backend": "cdp"})
    assert not_ready["ready"] is False
    assert "runtime_backend_not_playwright" in not_ready["issues"]
    assert "transport_mode_not_mcp" in not_ready["issues"]
    assert "mcp_endpoint_missing" in not_ready["issues"]


def test_cli_check_config_reports_not_ready_for_default_cdp():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.json"
        cfg_path.write_text(json.dumps({"capabilities": {"browser_control": {"runtime_backend": "cdp"}}}), encoding="utf-8")

        out = _run_cli(["--config-file", str(cfg_path), "check-config"])
        assert out.returncode == 0
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is True
        assert payload["browser_control"]["ready"] is False
        assert "runtime_backend_not_playwright" in payload["browser_control"]["issues"]


def test_cli_check_config_reports_ready_for_mcp_with_endpoint():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "capabilities": {
                        "browser_control": {
                            "runtime_backend": "playwright",
                            "playwright_transport_mode": "mcp",
                            "playwright_mcp_endpoint": "http://127.0.0.1:8787",
                            "playwright_mcp_fallback_to_local": True,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        out = _run_cli(["--config-file", str(cfg_path), "check-config"])
        assert out.returncode == 0
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is True
        assert payload["browser_control"]["ready"] is True
        assert payload["browser_control"]["issues"] == []
        assert payload["browser_control"]["warnings"] == ["mcp_fallback_enabled"]


def test_cli_check_config_fails_for_missing_file():
    out = _run_cli(["--config-file", "/tmp/does-not-exist-config.json", "check-config"])
    assert out.returncode == 2
    payload = json.loads(out.stdout.strip())
    assert payload["ok"] is False
    assert payload["error_code"] == "CONFIG_NOT_FOUND"
