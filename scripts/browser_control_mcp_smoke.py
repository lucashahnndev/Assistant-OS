#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict, Optional, Type

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from scripts.browser_control_mcp_preflight import (  # noqa: E402
    _extract_browser_control_cfg,
    _load_json,
    analyze_browser_control_mcp_readiness,
    cmd_probe_endpoint,
)
from src.capabilities.browser_control.browser_control_capability import (  # noqa: E402
    BrowserControlCapability,
)


class _KernelStub:
    config = {"agent": {"agent_name": "SmokeRunner"}}
    browser_session_registry = None


def _build_context(goal: str) -> Dict[str, Any]:
    return {
        "session_id": "smoke-session",
        "work_id": "smoke-work",
        "original_user_input": goal,
        "callbacks": {},
    }


def run_smoke(
    args: argparse.Namespace,
    *,
    capability_cls: Type[Any] = BrowserControlCapability,
) -> Dict[str, Any]:
    config_file = str(args.config_file or "").strip()
    if not config_file:
        return {"ok": False, "error_code": "MISSING_CONFIG_PATH"}
    if not os.path.exists(config_file):
        return {"ok": False, "error_code": "CONFIG_NOT_FOUND", "config_file": config_file}

    cfg = _load_json(config_file)
    browser_cfg = _extract_browser_control_cfg(cfg)
    readiness = analyze_browser_control_mcp_readiness(browser_cfg)
    report: Dict[str, Any] = {
        "ok": True,
        "mode": "smoke",
        "config_file": config_file,
        "readiness": readiness,
        "stages": {},
    }

    if bool(args.require_ready) and not readiness.get("ready"):
        report["ok"] = False
        report["error_code"] = "MCP_NOT_READY"
    if bool(args.fail_on_warnings) and readiness.get("warnings"):
        report["ok"] = False
        report["error_code"] = "MCP_WARNINGS_PRESENT"
    if not report["ok"]:
        return report

    if not bool(args.skip_endpoint_probe):
        endpoint = str(args.endpoint or readiness.get("playwright_mcp_endpoint") or "").strip()
        probe_args = Namespace(endpoint=endpoint, timeout_s=float(args.timeout_s), navigate_url=str(args.navigate_url or ""))
        probe = cmd_probe_endpoint(probe_args)
        report["stages"]["probe_endpoint"] = probe
        if not probe.get("ok"):
            report["ok"] = False
            report["error_code"] = "MCP_PROBE_FAILED"
            return report

    if bool(args.skip_run):
        report["stages"]["run"] = {"ok": True, "skipped": True}
        return report

    cap = capability_cls(_KernelStub(), browser_cfg if isinstance(browser_cfg, dict) else {})
    goal = str(args.goal or "").strip()
    intent_class = str(args.intent_class or "").strip().lower()
    run_ctx = _build_context(goal)
    run_params = {"goal": goal, "intent_class": intent_class, "headless": bool(args.headless)}
    close_payload: Optional[Dict[str, Any]] = None
    try:
        run_out = cap.execute("browser.control.run", run_params, run_ctx)
        report["stages"]["run"] = run_out if isinstance(run_out, dict) else {"ok": False, "error": "invalid_run_payload"}
        if not isinstance(run_out, dict) or not run_out.get("ok"):
            report["ok"] = False
            report["error_code"] = "RUN_FAILED"
            return report

        inspect_out = cap.execute("browser.control.inspect", {}, run_ctx)
        sync_out = cap.execute("browser.control.sync_registry", {}, run_ctx)
        health_out = cap.execute("browser.control.health", {"run_gc": False}, run_ctx)
        report["stages"]["inspect"] = inspect_out if isinstance(inspect_out, dict) else {"ok": False}
        report["stages"]["sync_registry"] = sync_out if isinstance(sync_out, dict) else {"ok": False}
        report["stages"]["health"] = health_out if isinstance(health_out, dict) else {"ok": False}
    finally:
        try:
            close_out = cap.execute("browser.control.close", {}, run_ctx)
            close_payload = close_out if isinstance(close_out, dict) else {"ok": True}
        except Exception as e:
            close_payload = {"ok": False, "error": str(e)}
    report["stages"]["close"] = close_payload or {"ok": True}
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browser Control MCP + Playwright smoke runner")
    parser.add_argument("--config-file", default=os.path.join(str(ROOT), "data", "config.json"))
    parser.add_argument("--goal", default="Abrir uma página de teste e validar operação básica.")
    parser.add_argument("--intent-class", default="automacao_ui")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--navigate-url", default="")
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--skip-endpoint-probe", action="store_true")
    parser.add_argument("--skip-run", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--fail-on-warnings", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = run_smoke(args)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
