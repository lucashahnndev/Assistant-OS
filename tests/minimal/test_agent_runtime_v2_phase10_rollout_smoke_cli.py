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

from src.services.agent_runtime_v2 import PolicyRolloutEngine


class _Cfg:
    def __init__(self, base_data_dir: str):
        self.base_data_dir = base_data_dir

    def get(self, key, default=None):
        return default


def _run_cli(args, cwd=None):
    cmd = [
        str(ROOT / "env" / "bin" / "python"),
        str(ROOT / "scripts" / "runtime_v2_rollout_smoke.py"),
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd or ROOT), check=False)


def test_rollout_smoke_cli_check_and_canary_abort_flow():
    with tempfile.TemporaryDirectory() as tmp:
        engine = PolicyRolloutEngine(config_manager=_Cfg(tmp))
        engine.create_draft(policy_id="cli-p1", policy_cfg={"mode": "enforce"})
        engine.mark_simulated(policy_id="cli-p1", simulation_result={})
        engine.start_canary(policy_id="cli-p1", tenant_ids=["tenant-a"], rollout_percent=10)

        check = _run_cli(["--base-data-dir", tmp, "check", "--policy-id", "cli-p1"])
        assert check.returncode == 0
        check_payload = json.loads(check.stdout.strip())
        assert check_payload["ok"] is True
        assert check_payload["state"] == "canary"

        abort = _run_cli(
            [
                "--base-data-dir",
                tmp,
                "canary-check",
                "--policy-id",
                "cli-p1",
                "--error-rate",
                "0.9",
                "--latency-increase",
                "0.1",
                "--max-error-rate",
                "0.2",
                "--max-latency-increase",
                "0.5",
            ]
        )
        assert abort.returncode == 0
        abort_payload = json.loads(abort.stdout.strip())
        assert abort_payload["ok"] is True
        assert abort_payload["abort"] is True

        post_engine = PolicyRolloutEngine(config_manager=_Cfg(tmp))
        post = post_engine.get_policy("cli-p1")
        assert post.get("state") == "rolled_back"


def test_rollout_smoke_cli_rollback_check_for_active_policy():
    with tempfile.TemporaryDirectory() as tmp:
        engine = PolicyRolloutEngine(config_manager=_Cfg(tmp))
        engine.create_draft(policy_id="cli-p2", policy_cfg={"mode": "enforce"})
        engine.mark_simulated(policy_id="cli-p2", simulation_result={})
        engine.start_canary(policy_id="cli-p2", tenant_ids=["tenant-a"], rollout_percent=10)
        engine.promote_active(policy_id="cli-p2", tenant_ids=["tenant-a"])

        rb = _run_cli(
            [
                "--base-data-dir",
                tmp,
                "rollback-check",
                "--policy-id",
                "cli-p2",
                "--reason",
                "test_rollback",
            ]
        )
        assert rb.returncode == 0
        rb_payload = json.loads(rb.stdout.strip())
        assert rb_payload["ok"] is True
        assert rb_payload["state"] == "rolled_back"
