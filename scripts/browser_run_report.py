#!/usr/bin/env python3
"""Generate a structured browser-agent run report from local logs.

Output is a human-readable markdown report with:
- planner action timeline
- progress snapshots
- vision/perception feedback
- CDP execution evidence (keys/clicks/scroll/nav)
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - ")
TRACE_RE = re.compile(r'"trace_id":\s*"([^"]+)"')
STEP_BANNER_RE = re.compile(r"--- \[ (STEP_\d+) \] ---")
THOUGHT_RE = re.compile(r"\[(step_\d+)\].*🧠 THOUGHT: (.*)$")
ACTION_RE = re.compile(r"\[(step_\d+)\].*🎯 ACTION: ([^(]+)\((.*)\)$")
FUSED_RE = re.compile(r"\[Perception\] Fused State: (\d+) Candidates \| Confidence: ([0-9.]+)")
VISION_RE = re.compile(r"\[Vision\] Observer Feedback: (.*)$")
LOOP_RE = re.compile(r"Loop Detection")


@dataclass
class StepData:
    step: str
    thought: str | None = None
    action_name: str | None = None
    action_args: Any = None
    progress: list[str] = field(default_factory=list)
    fused_state: list[dict[str, Any]] = field(default_factory=list)
    vision_feedback: list[str] = field(default_factory=list)
    loop_warnings: int = 0
    cdp_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RunData:
    trace_id: str
    session_id: str | None = None
    work_id: str | None = None
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    steps: dict[str, StepData] = field(default_factory=dict)

    def ensure_step(self, step: str) -> StepData:
        if step not in self.steps:
            self.steps[step] = StepData(step=step)
        return self.steps[step]


def _parse_ts(line: str) -> datetime | None:
    m = TS_RE.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _safe_eval_args(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return {}
    try:
        return ast.literal_eval(raw)
    except Exception:
        return raw


def _truncate(s: str, max_len: int = 260) -> str:
    s = " ".join(s.split())
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def _step_key(step: str) -> int:
    try:
        return int(step.split("_", 1)[1])
    except Exception:
        return 0


def find_latest_trace(assistant_log: Path) -> str | None:
    last = None
    with assistant_log.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = TRACE_RE.search(line)
            if m:
                last = m.group(1)
    return last


def find_trace_window(assistant_log: Path, trace_id: str) -> tuple[datetime | None, datetime | None]:
    start: datetime | None = None
    end: datetime | None = None
    with assistant_log.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if trace_id not in line:
                continue
            ts = _parse_ts(line)
            if ts is None:
                continue
            if start is None:
                start = ts
            end = ts
    return start, end


def parse_assistant_window(assistant_log: Path, run: RunData) -> None:
    current_step: str | None = None
    capture_progress = False
    progress_buf: list[str] = []

    with assistant_log.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            ts = _parse_ts(line)
            if ts is None or run.start_ts is None or run.end_ts is None:
                continue
            if ts < run.start_ts or ts > run.end_ts:
                continue

            if run.session_id is None:
                sm = re.search(r'"session_id":\s*"([^"]*)"', line)
                if sm:
                    run.session_id = sm.group(1)
            if run.work_id is None:
                wm = re.search(r'"work_id":\s*"([^"]*)"', line)
                if wm:
                    run.work_id = wm.group(1)

            bm = STEP_BANNER_RE.search(line)
            if bm:
                current_step = bm.group(1).lower()
                run.ensure_step(current_step)

            tm = THOUGHT_RE.search(line)
            if tm:
                current_step = tm.group(1)
                run.ensure_step(current_step).thought = tm.group(2).strip()

            am = ACTION_RE.search(line)
            if am:
                current_step = am.group(1)
                sd = run.ensure_step(current_step)
                sd.action_name = am.group(2).strip()
                sd.action_args = _safe_eval_args(am.group(3))

            if "CURRENT PROGRESS:" in line:
                capture_progress = True
                progress_buf = []
                continue

            if capture_progress:
                stripped = line.strip()
                if stripped.startswith("["):
                    progress_buf.append(stripped)
                    continue
                capture_progress = False
                if current_step and progress_buf:
                    run.ensure_step(current_step).progress = progress_buf[:]

            fm = FUSED_RE.search(line)
            if fm and current_step:
                run.ensure_step(current_step).fused_state.append(
                    {"candidates": int(fm.group(1)), "confidence": float(fm.group(2))}
                )

            vm = VISION_RE.search(line)
            if vm and current_step:
                run.ensure_step(current_step).vision_feedback.append(vm.group(1).strip())

            if LOOP_RE.search(line) and current_step:
                run.ensure_step(current_step).loop_warnings += 1


def attach_cdp_events_from_assistant(assistant_log: Path, run: RunData) -> None:
    with assistant_log.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if run.trace_id not in line or "cdp.request" not in line:
                continue
            sm = re.search(r'"step_id":\s*"([^"]+)"', line)
            mm = re.search(r'"method":\s*"([^"]+)"', line)
            if not sm or not mm:
                continue
            step = sm.group(1)
            method = mm.group(1)
            if step not in run.steps:
                run.ensure_step(step)

            ev: dict[str, Any] | None = None
            if method == "Input.dispatchMouseEvent":
                pm = re.search(r'"params":\s*(\{.*\})\s*}$', line)
                if pm:
                    try:
                        params = json.loads(pm.group(1))
                        t = params.get("type")
                        if t in {"mousePressed", "mouseReleased", "mouseWheel"}:
                            ev = {
                                "method": method,
                                "type": t,
                                "x": params.get("x"),
                                "y": params.get("y"),
                                "button": params.get("button"),
                                "deltaY": params.get("deltaY"),
                            }
                    except Exception:
                        pass
            elif method == "Input.dispatchKeyEvent":
                pm = re.search(r'"params":\s*(\{.*\})\s*}$', line)
                if pm:
                    try:
                        params = json.loads(pm.group(1))
                        ev = {
                            "method": method,
                            "type": params.get("type"),
                            "key": params.get("key"),
                            "code": params.get("code"),
                        }
                    except Exception:
                        pass
            elif method == "Page.navigate":
                pm = re.search(r'"params":\s*(\{.*\})\s*}$', line)
                if pm:
                    try:
                        params = json.loads(pm.group(1))
                        ev = {"method": method, "url": params.get("url")}
                    except Exception:
                        pass

            if ev is not None:
                run.steps[step].cdp_events.append(ev)


def build_markdown(run: RunData) -> str:
    steps = [run.steps[k] for k in sorted(run.steps.keys(), key=_step_key)]
    lines: list[str] = []
    lines.append("# Browser Run Report")
    lines.append("")
    lines.append(f"- trace_id: `{run.trace_id or 'unknown'}`")
    lines.append(f"- session_id: `{run.session_id or 'unknown'}`")
    lines.append(f"- work_id: `{run.work_id or 'unknown'}`")
    lines.append(
        f"- window: `{run.start_ts.strftime('%Y-%m-%d %H:%M:%S') if run.start_ts else 'unknown'}` -> "
        f"`{run.end_ts.strftime('%Y-%m-%d %H:%M:%S') if run.end_ts else 'unknown'}`"
    )
    lines.append(f"- steps_analyzed: `{len(steps)}`")
    lines.append("")

    actions: dict[str, int] = {}
    for s in steps:
        if s.action_name:
            actions[s.action_name] = actions.get(s.action_name, 0) + 1
    if actions:
        lines.append("## Action Summary")
        for k in sorted(actions):
            lines.append(f"- {k}: {actions[k]}")
        lines.append("")

    lines.append("## Step Timeline")
    for s in steps:
        lines.append(f"### {s.step}")
        if s.action_name:
            lines.append(f"- planner_action: `{s.action_name}`")
            lines.append(f"- planner_args: `{s.action_args}`")
        if s.thought:
            lines.append(f"- planner_thought: {_truncate(s.thought)}")
        if s.progress:
            lines.append("- progress_snapshot:")
            for p in s.progress:
                lines.append(f"  - {p}")
        if s.fused_state:
            last = s.fused_state[-1]
            lines.append(f"- fused_state: candidates={last['candidates']}, confidence={last['confidence']}")
        if s.vision_feedback:
            lines.append(f"- vision_feedback: {_truncate(s.vision_feedback[-1])}")
        if s.loop_warnings:
            lines.append(f"- loop_warnings: {s.loop_warnings}")
        if s.cdp_events:
            lines.append("- cdp_evidence:")
            for ev in s.cdp_events[:15]:
                lines.append(f"  - `{ev}`")
            if len(s.cdp_events) > 15:
                lines.append(f"  - ... +{len(s.cdp_events) - 15} events")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate browser run report from assistant log")
    parser.add_argument("--assistant-log", default="data/logs/assistant.log")
    parser.add_argument("--trace-id", default="", help="Trace id to analyze; default uses latest")
    parser.add_argument("--out", default="", help="Output markdown path")
    parser.add_argument("--follow", action="store_true", help="Continuously update report as log grows")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds for --follow")
    args = parser.parse_args()

    assistant_log = Path(args.assistant_log)
    if not assistant_log.exists():
        raise SystemExit(f"assistant log not found: {assistant_log}")

    trace_id = args.trace_id.strip() or find_latest_trace(assistant_log)
    if not trace_id:
        raise SystemExit("Could not find trace_id in assistant log")

    out = Path(args.out) if args.out else Path("data/logs") / f"browser_run_report_{trace_id}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    def render_once(target_trace_id: str) -> tuple[bool, str]:
        run = RunData(trace_id=target_trace_id)
        run.start_ts, run.end_ts = find_trace_window(assistant_log, target_trace_id)
        if run.start_ts is None or run.end_ts is None:
            return False, target_trace_id
        parse_assistant_window(assistant_log, run)
        attach_cdp_events_from_assistant(assistant_log, run)
        out.write_text(build_markdown(run), encoding="utf-8")
        return True, target_trace_id

    if not args.follow:
        ok, _ = render_once(trace_id)
        if not ok:
            raise SystemExit(f"trace_id not found in log: {trace_id}")
        print(str(out))
        return 0

    print(f"Following assistant log. Writing report to: {out}")
    print("Press Ctrl+C to stop.")
    last_size = -1
    active_trace = trace_id
    try:
        while True:
            try:
                current_size = assistant_log.stat().st_size
            except FileNotFoundError:
                current_size = -1
            if current_size != last_size:
                last_size = current_size
                latest_trace = args.trace_id.strip() or find_latest_trace(assistant_log)
                if latest_trace:
                    active_trace = latest_trace
                ok, _ = render_once(active_trace)
                if ok:
                    print(f"[updated] trace={active_trace} size={current_size}")
            time.sleep(max(args.interval, 0.2))
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
