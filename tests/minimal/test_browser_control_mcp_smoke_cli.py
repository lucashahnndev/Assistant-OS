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

import scripts.browser_control_mcp_smoke as smoke


def _run_cli(args):
    cmd = [
        str(ROOT / "env" / "bin" / "python"),
        str(ROOT / "scripts" / "browser_control_mcp_smoke.py"),
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=False)


def test_smoke_cli_fails_when_config_missing():
    out = _run_cli(["--config-file", "/tmp/does-not-exist-config.json", "--skip-endpoint-probe", "--skip-run"])
    assert out.returncode == 2
    payload = json.loads(out.stdout.strip())
    assert payload["ok"] is False
    assert payload["error_code"] == "CONFIG_NOT_FOUND"


def test_smoke_cli_require_ready_blocks_non_playwright_config():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.json"
        cfg.write_text(json.dumps({"capabilities": {"browser_control": {"runtime_backend": "cdp"}}}), encoding="utf-8")
        out = _run_cli(["--config-file", str(cfg), "--skip-endpoint-probe", "--skip-run", "--require-ready"])
        assert out.returncode == 2
        payload = json.loads(out.stdout.strip())
        assert payload["ok"] is False
        assert payload["error_code"] == "MCP_NOT_READY"


def test_run_smoke_returns_success_with_fake_capability_and_probe(monkeypatch):
    class _FakeCap:
        def __init__(self, _kernel, _cfg):
            pass

        def execute(self, action_id, _params, _context):
            if action_id == "browser.control.run":
                return {"ok": True, "execution_context": {"runtime_backend": "playwright"}}
            if action_id == "browser.control.inspect":
                return {"ok": True, "current_execution": {"runtime_backend": "playwright"}}
            if action_id == "browser.control.sync_registry":
                return {"ok": True, "runtime_backend": "playwright", "transport_mode_effective": "mcp"}
            if action_id == "browser.control.health":
                return {"ok": True, "health": {"issues": []}}
            if action_id == "browser.control.close":
                return {"ok": True}
            return {"ok": False}

    def _fake_probe(_args):
        return {"ok": True, "mode": "probe-endpoint", "mcp_calls_total": 1}

    monkeypatch.setattr(smoke, "cmd_probe_endpoint", _fake_probe)

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.json"
        cfg.write_text(
            json.dumps(
                {
                    "capabilities": {
                        "browser_control": {
                            "runtime_backend": "playwright",
                            "playwright_transport_mode": "mcp",
                            "playwright_mcp_endpoint": "http://127.0.0.1:8787",
                            "playwright_mcp_fallback_to_local": False,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        args = smoke.build_parser().parse_args(
            [
                "--config-file",
                str(cfg),
                "--goal",
                "Teste de smoke",
                "--intent-class",
                "automacao_ui",
            ]
        )
        out = smoke.run_smoke(args, capability_cls=_FakeCap)
        assert out["ok"] is True
        assert out["stages"]["probe_endpoint"]["ok"] is True
        assert out["stages"]["run"]["ok"] is True
        assert out["stages"]["inspect"]["ok"] is True
        assert out["stages"]["sync_registry"]["transport_mode_effective"] == "mcp"
        assert out["stages"]["close"]["ok"] is True
