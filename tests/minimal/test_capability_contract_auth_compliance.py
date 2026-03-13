import json
import os
import subprocess
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_capability_contract_auth_compliance_checker_passes():
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT_DIR, "scripts", "check_capability_contracts.py")],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr

    payload = json.loads(result.stdout)
    assert payload["contracts"] >= 1
    assert payload["issues"] == 0
