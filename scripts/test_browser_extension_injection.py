#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
import tempfile
import shutil
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.capabilities.browser_control.runtime import BrowserRuntime  # noqa: E402


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


async def _read_page_diag(runtime: BrowserRuntime) -> Dict[str, Any]:
    expr = r"""
    (() => {
      const ds = document.documentElement.dataset;
      const host = document.getElementById("agent-host");
      return {
        url: String(window.location.href || ""),
        ready_state: String(document.readyState || ""),
        host_present: !!host,
        guard_installed: String(ds.agentGuardInstalled || "") === "true",
        content_script_loaded: String(ds.agentContentScriptLoaded || "") === "true",
        active: String(ds.agentActive || "") === "true",
        paused: String(ds.agentPaused || "") === "true",
        resume_requested: String(ds.agentResumeRequested || "") === "true",
        has_sync_payload: !!String(ds.agentControlSync || ""),
      };
    })()
    """
    res = await runtime._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    value = res.get("result", {}).get("value", {})
    return value if isinstance(value, dict) else {}


def _read_debug_targets(debug_port: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "count": 0, "extension_targets": []}
    url = f"http://127.0.0.1:{int(debug_port)}/json/list"
    try:
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        if not isinstance(payload, list):
            out["error"] = "unexpected_payload"
            return out
        ext = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_url = str(item.get("url") or "")
            if item_url.startswith("chrome-extension://"):
                ext.append(
                    {
                        "id": str(item.get("id") or ""),
                        "type": str(item.get("type") or ""),
                        "url": item_url,
                        "title": str(item.get("title") or ""),
                    }
                )
        out["ok"] = True
        out["count"] = len(payload)
        out["extension_targets"] = ext
        return out
    except urllib.error.URLError as exc:
        out["error"] = f"url_error:{exc}"
        return out
    except Exception as exc:
        out["error"] = str(exc)
        return out


async def run_forced_injection_check(args: argparse.Namespace) -> int:
    report: Dict[str, Any] = {
        "started_at": _now_iso(),
        "url": args.url,
        "headless": bool(args.headless),
        "chrome_path": args.chrome_path,
        "ok": False,
        "checks": {},
    }

    temp_root = ""
    if args.base_profile_path:
        base_profile_path = str(Path(args.base_profile_path).resolve())
        overlay_profile_parent = str(Path(args.overlay_profile_parent or (Path(base_profile_path) / "sessions")).resolve())
    else:
        temp_root = tempfile.mkdtemp(prefix="aosd-browser-test-")
        base_profile_path = str(Path(temp_root) / "profile")
        overlay_profile_parent = str(Path(temp_root) / "overlay")
    os.makedirs(base_profile_path, exist_ok=True)
    os.makedirs(overlay_profile_parent, exist_ok=True)

    runtime = BrowserRuntime(
        chrome_path=args.chrome_path,
        base_profile_path=base_profile_path,
        overlay_profile_parent=overlay_profile_parent,
        headless=bool(args.headless),
        muted=True,
        app_mode=False,
        launch_url="about:blank",
        extension_install_mode=str(args.extension_install_mode or "auto"),
        extension_fallback_enabled=not bool(args.disable_extension_fallback),
    )

    try:
        await runtime.launch()
        await runtime.navigate(args.url)
        await asyncio.sleep(args.settle_seconds)
        targets_diag = _read_debug_targets(int(runtime.remote_debugging_port or 0))

        await runtime.set_agent_control_active(True)
        await asyncio.sleep(args.settle_seconds)
        active_state = await runtime._read_control_overlay_state()
        active_diag = await _read_page_diag(runtime)

        await runtime.set_agent_control_active(False)
        await asyncio.sleep(args.settle_seconds)
        inactive_state = await runtime._read_control_overlay_state()
        inactive_diag = await _read_page_diag(runtime)

        extension_detected = bool(targets_diag.get("extension_targets"))
        checks = {
            "extension_target_detected": extension_detected,
            "host_injected": bool(active_diag.get("host_present")),
            "guard_installed": bool(active_diag.get("guard_installed")),
            "content_script_loaded": bool(active_diag.get("content_script_loaded")),
            "sync_payload_present": bool(active_diag.get("has_sync_payload")),
            "active_state_reflected": bool(active_state.get("active")),
            "active_overlay_visible_bar": bool(active_state.get("bar_visible")),
            "active_overlay_visible_cursor": bool(active_state.get("cursor_visible")),
            "inactive_state_reflected": not bool(inactive_state.get("active")),
        }
        if not bool(args.require_extension_target):
            checks.pop("extension_target_detected", None)
        ok = all(checks.values())

        report.update(
            {
                "ok": ok,
                "checks": checks,
                "active_overlay_state": active_state,
                "inactive_overlay_state": inactive_state,
                "active_page_diag": active_diag,
                "inactive_page_diag": inactive_diag,
                "targets_diag": targets_diag,
                "connection": runtime.get_connection_metadata(),
            }
        )
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        report["finished_at"] = _now_iso()
        try:
            await runtime.close()
        except Exception as close_exc:
            report["close_error"] = str(close_exc)
        if temp_root:
            try:
                shutil.rmtree(temp_root, ignore_errors=True)
            except Exception:
                pass

    out_path = Path(args.report_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Report: {out_path}")
    print(f"Result: {'PASS' if report.get('ok') else 'FAIL'}")
    if isinstance(report.get("checks"), dict):
        for key, value in report["checks"].items():
            print(f" - {key}: {value}")
    if report.get("error"):
        print(f"Error: {report['error']}")
    return 0 if report.get("ok") else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Forced extension injection test for browser_control runtime (no LLM, no full system)."
    )
    parser.add_argument("--url", default="https://example.com", help="Target URL to validate extension injection.")
    parser.add_argument("--headless", action="store_true", help="Run Chrome in headless mode.")
    parser.add_argument("--chrome-path", default="/usr/bin/google-chrome", help="Chrome executable path.")
    parser.add_argument("--base-profile-path", default="", help="Optional explicit browser profile path for the test.")
    parser.add_argument("--overlay-profile-parent", default="", help="Optional explicit overlay/session profile parent.")
    parser.add_argument(
        "--extension-install-mode",
        default="auto",
        choices=["auto", "sideload_only", "fallback_only"],
        help="How runtime should install/load the extension.",
    )
    parser.add_argument(
        "--disable-extension-fallback",
        action="store_true",
        help="Disable runtime fallback injection path and rely only on extension sideload.",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=1.0,
        help="Seconds to wait after navigation and state toggles.",
    )
    parser.add_argument(
        "--report-path",
        default="data/browser_data/extension_injection_report.json",
        help="Path for JSON report output.",
    )
    parser.add_argument(
        "--require-extension-target",
        action="store_true",
        help="Fail if no chrome-extension:// target is detected in /json/list.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(run_forced_injection_check(args))


if __name__ == "__main__":
    raise SystemExit(main())
