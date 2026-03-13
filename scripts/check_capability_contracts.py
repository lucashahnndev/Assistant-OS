#!/usr/bin/env python3
import json
import os
import sys
from typing import Any, Dict, List


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from capabilities.contract_v1 import (  # noqa: E402
    load_contract_config_schema,
    load_contract_v1,
    validate_auth_schema_alignment,
)


CAPABILITIES_DIR = os.path.join(SRC_DIR, "capabilities")


def _find_legacy_x_secret(schema: Any, path: str = "$") -> List[str]:
    issues: List[str] = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            child_path = f"{path}.{key}"
            if key == "x-secret":
                issues.append(child_path)
            issues.extend(_find_legacy_x_secret(value, child_path))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            issues.extend(_find_legacy_x_secret(value, f"{path}[{index}]"))
    return issues


def main() -> int:
    rows: List[Dict[str, Any]] = []
    issues: List[str] = []

    for entry in sorted(os.listdir(CAPABILITIES_DIR)):
        contract_path = os.path.join(CAPABILITIES_DIR, entry, "contract.json")
        if not os.path.exists(contract_path):
            continue

        contract = load_contract_v1(contract_path)
        schema = load_contract_config_schema(contract_path, contract)
        auth_schema_issues = validate_auth_schema_alignment(contract, schema)
        schema_legacy_issues = _find_legacy_x_secret(schema) if schema is not None else []

        row = {
            "capability_id": contract.capability.id,
            "auth_mode": contract.auth.mode,
            "auth_fields": len(contract.auth.fields),
            "schema_present": schema is not None,
            "legacy_x_secret_count": len(schema_legacy_issues),
            "issues": auth_schema_issues + [f"legacy x-secret present at {item}" for item in schema_legacy_issues],
        }
        rows.append(row)
        for item in row["issues"]:
            issues.append(f"{contract.capability.id}: {item}")

    summary = {
        "contracts": len(rows),
        "issues": len(issues),
        "rows": rows,
    }
    print(json.dumps(summary, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
