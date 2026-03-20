#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from scripts.browser_control_mcp_smoke import run_smoke


def _load_json_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return raw if isinstance(raw, dict) else {}


def evaluate_gate(
    smoke: Dict[str, Any],
    *,
    allow_local_fallback: bool,
    min_mcp_calls: int,
    allowed_health_issues: List[str],
) -> Tuple[bool, List[Dict[str, Any]]]:
    checks: List[Dict[str, Any]] = []

    def add(name: str, passed: bool, details: Dict[str, Any] | None = None) -> None:
        checks.append({"name": name, "passed": bool(passed), "details": details or {}})

    add("smoke_ok", bool(smoke.get("ok")), {"smoke_error_code": smoke.get("error_code")})

    stages = smoke.get("stages") if isinstance(smoke.get("stages"), dict) else {}
    run_stage = stages.get("run") if isinstance(stages.get("run"), dict) else {}
    inspect_stage = stages.get("inspect") if isinstance(stages.get("inspect"), dict) else {}
    sync_stage = stages.get("sync_registry") if isinstance(stages.get("sync_registry"), dict) else {}
    health_stage = stages.get("health") if isinstance(stages.get("health"), dict) else {}
    probe_stage = stages.get("probe_endpoint") if isinstance(stages.get("probe_endpoint"), dict) else {}

    add("run_ok", bool(run_stage.get("ok")), {})
    add("inspect_ok", bool(inspect_stage.get("ok")), {})
    add("sync_registry_ok", bool(sync_stage.get("ok")), {})
    add("health_ok", bool(health_stage.get("ok")), {})
    if probe_stage:
        add("probe_endpoint_ok", bool(probe_stage.get("ok")), {})

    runtime_backend = str(sync_stage.get("runtime_backend") or "").strip().lower()
    transport_effective = str(sync_stage.get("transport_mode_effective") or "").strip().lower()
    mcp_calls_total = int(sync_stage.get("mcp_calls_total") or 0)
    add("runtime_backend_playwright", runtime_backend == "playwright", {"runtime_backend": runtime_backend})
    if allow_local_fallback:
        add(
            "transport_effective_mcp_or_local",
            transport_effective in {"mcp", "local"},
            {"transport_mode_effective": transport_effective},
        )
    else:
        add(
            "transport_effective_mcp",
            transport_effective == "mcp",
            {"transport_mode_effective": transport_effective},
        )
    add(
        "mcp_calls_threshold",
        mcp_calls_total >= int(min_mcp_calls),
        {"mcp_calls_total": mcp_calls_total, "min_mcp_calls": int(min_mcp_calls)},
    )

    health = health_stage.get("health") if isinstance(health_stage.get("health"), dict) else {}
    issues = [str(x) for x in (health.get("issues") or [])]
    blocked = [x for x in issues if x not in set(allowed_health_issues)]
    add(
        "health_issues_allowed",
        len(blocked) == 0,
        {"issues": issues, "allowed_health_issues": list(allowed_health_issues), "blocked_issues": blocked},
    )

    passed = all(bool(c.get("passed")) for c in checks)
    return passed, checks


def cmd_gate(args: argparse.Namespace) -> Dict[str, Any]:
    smoke_report_file = str(args.smoke_report_file or "").strip()
    if smoke_report_file:
        if not os.path.exists(smoke_report_file):
            return {"ok": False, "mode": "gate", "error_code": "SMOKE_REPORT_NOT_FOUND", "smoke_report_file": smoke_report_file}
        smoke = _load_json_file(smoke_report_file)
    else:
        smoke_args = Namespace(
            config_file=args.config_file,
            goal=args.goal,
            intent_class=args.intent_class,
            headless=bool(args.headless),
            endpoint=args.endpoint,
            navigate_url=args.navigate_url,
            timeout_s=float(args.timeout_s),
            skip_endpoint_probe=bool(args.skip_endpoint_probe),
            skip_run=bool(args.skip_run),
            require_ready=bool(args.require_ready),
            fail_on_warnings=bool(args.fail_on_warnings),
        )
        smoke = run_smoke(smoke_args)

    allowed = [str(x).strip() for x in (args.allow_health_issue or []) if str(x).strip()]
    passed, checks = evaluate_gate(
        smoke,
        allow_local_fallback=bool(args.allow_local_fallback),
        min_mcp_calls=int(args.min_mcp_calls),
        allowed_health_issues=allowed,
    )
    return {
        "ok": bool(passed),
        "mode": "gate",
        "error_code": "" if passed else "CI_GATE_FAILED",
        "checks": checks,
        "smoke": smoke,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browser Control MCP/Playwright CI gate")
    parser.add_argument("--smoke-report-file", default="")
    parser.add_argument("--config-file", default=os.path.join(str(ROOT), "data", "config.json"))
    parser.add_argument("--goal", default="Abra https://example.com e valide o título da página.")
    parser.add_argument("--intent-class", default="automacao_ui")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--navigate-url", default="")
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--skip-endpoint-probe", action="store_true")
    parser.add_argument("--skip-run", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--fail-on-warnings", action="store_true")
    parser.add_argument("--allow-local-fallback", action="store_true")
    parser.add_argument("--min-mcp-calls", type=int, default=1)
    parser.add_argument("--allow-health-issue", action="append", default=[])
    parser.set_defaults(handler=cmd_gate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = args.handler(args)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
