#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.capabilities.browser_control.playwright_mcp_adapter import PlaywrightMCPAdapter


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _extract_browser_control_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    caps = cfg.get("capabilities") if isinstance(cfg.get("capabilities"), dict) else {}
    bc = caps.get("browser_control") if isinstance(caps.get("browser_control"), dict) else {}
    return dict(bc)


def analyze_browser_control_mcp_readiness(browser_cfg: Dict[str, Any]) -> Dict[str, Any]:
    runtime_backend = str(browser_cfg.get("runtime_backend", "cdp") or "cdp").strip().lower()
    transport_mode = str(browser_cfg.get("playwright_transport_mode", "local") or "local").strip().lower()
    endpoint = str(browser_cfg.get("playwright_mcp_endpoint", "") or "").strip()
    fallback = bool(browser_cfg.get("playwright_mcp_fallback_to_local", True))

    issues = []
    warnings = []

    if runtime_backend != "playwright":
        issues.append("runtime_backend_not_playwright")
    if transport_mode != "mcp":
        issues.append("transport_mode_not_mcp")
    if not endpoint:
        issues.append("mcp_endpoint_missing")
    elif not (endpoint.startswith("http://") or endpoint.startswith("https://")):
        warnings.append("mcp_endpoint_unusual_scheme")
    if fallback:
        warnings.append("mcp_fallback_enabled")

    return {
        "runtime_backend": runtime_backend,
        "playwright_transport_mode": transport_mode,
        "playwright_mcp_endpoint": endpoint,
        "playwright_mcp_fallback_to_local": fallback,
        "ready": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
    }


def cmd_check_config(args: argparse.Namespace) -> Dict[str, Any]:
    path = str(args.config_file or "").strip()
    if not path:
        return {"ok": False, "error_code": "MISSING_CONFIG_PATH"}
    if not os.path.exists(path):
        return {"ok": False, "error_code": "CONFIG_NOT_FOUND", "config_file": path}

    cfg = _load_json(path)
    browser_cfg = _extract_browser_control_cfg(cfg)
    readiness = analyze_browser_control_mcp_readiness(browser_cfg)
    payload = {
        "ok": True,
        "mode": "check-config",
        "config_file": path,
        "browser_control": readiness,
    }
    require_ready = bool(getattr(args, "require_ready", False))
    fail_on_warnings = bool(getattr(args, "fail_on_warnings", False))
    if require_ready and not readiness.get("ready"):
        payload["ok"] = False
        payload["error_code"] = "MCP_NOT_READY"
    if fail_on_warnings and readiness.get("warnings"):
        payload["ok"] = False
        payload["error_code"] = "MCP_WARNINGS_PRESENT"
    return payload


def cmd_probe_endpoint(args: argparse.Namespace) -> Dict[str, Any]:
    endpoint = str(args.endpoint or "").strip()
    if not endpoint:
        return {"ok": False, "error_code": "MISSING_ENDPOINT"}

    timeout_s = float(max(1.0, float(args.timeout_s or 10.0)))
    navigate_url = str(args.navigate_url or "").strip()

    adapter = PlaywrightMCPAdapter(endpoint=endpoint, timeout_s=timeout_s)
    t0 = time.time()
    try:
        if navigate_url:
            _ = asyncio.run(adapter.navigate(navigate_url))
        page_info = asyncio.run(adapter.get_page_info())
    except Exception as e:
        return {
            "ok": False,
            "mode": "probe-endpoint",
            "endpoint": endpoint,
            "error_code": "MCP_PROBE_FAILED",
            "error_details": str(e),
        }

    return {
        "ok": True,
        "mode": "probe-endpoint",
        "endpoint": endpoint,
        "latency_ms": int((time.time() - t0) * 1000),
        "mcp_calls_total": int(adapter.calls_total),
        "page_info": page_info if isinstance(page_info, dict) else {},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browser Control Playwright MCP preflight utility")
    parser.add_argument(
        "--config-file",
        default=os.path.join(str(ROOT), "data", "config.json"),
        help="Path to config.json used by browser_control",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check-config", help="Validate browser_control MCP configuration readiness")
    p_check.add_argument("--require-ready", action="store_true")
    p_check.add_argument("--fail-on-warnings", action="store_true")
    p_check.set_defaults(handler=cmd_check_config)

    p_probe = sub.add_parser("probe-endpoint", help="Probe MCP endpoint via Playwright MCP adapter")
    p_probe.add_argument("--endpoint", required=True)
    p_probe.add_argument("--timeout-s", type=float, default=10.0)
    p_probe.add_argument("--navigate-url", default="")
    p_probe.set_defaults(handler=cmd_probe_endpoint)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = args.handler(args)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
