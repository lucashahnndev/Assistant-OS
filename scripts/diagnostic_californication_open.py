import datetime
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from config.manager import ConfigManager
from core.identity import PrincipalContext
from core.orchestrator import AgentOrchestrator


@dataclass
class TurnCapture:
    prompt: str
    started_at: float = 0.0
    ended_at: float = 0.0
    timed_out: bool = False
    process_return: Any = None
    exception: Optional[str] = None
    statuses: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: List[Dict[str, Any]] = field(default_factory=list)
    responses: List[Dict[str, Any]] = field(default_factory=list)


def run_turn(orch: AgentOrchestrator, session_id: str, prompt: str, timeout_s: int = 240) -> TurnCapture:
    cap = TurnCapture(prompt=prompt, started_at=time.time())
    out_box: Dict[str, Any] = {}

    def send_status(phase, payload=None):
        cap.statuses.append({"ts": time.time(), "phase": phase, "payload": payload})

    def send_reasoning_chunk(content):
        cap.reasoning.append({"ts": time.time(), "content": str(content)})

    def send_response(text, is_chunk=False, attachments=None):
        cap.responses.append(
            {"ts": time.time(), "text": str(text), "is_chunk": bool(is_chunk), "attachments": attachments}
        )

    callbacks = {
        "send_status": send_status,
        "send_reasoning_chunk": send_reasoning_chunk,
        "send_response": send_response,
        "send_complete": lambda: None,
    }
    ctx = PrincipalContext(interface="diagnostic", sender_id="diag_user", sender_name="diagnostic", session_id=session_id)

    def _runner():
        try:
            out_box["out"] = orch.process(prompt, session_id=session_id, callbacks=callbacks, context=ctx, user_data={})
        except Exception as exc:
            out_box["exc"] = repr(exc)

    th = threading.Thread(target=_runner, daemon=True)
    th.start()
    th.join(timeout=timeout_s)
    if th.is_alive():
        cap.timed_out = True
    cap.ended_at = time.time()
    cap.process_return = out_box.get("out")
    cap.exception = out_box.get("exc")
    return cap


def _extract_action_records(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    pattern = re.compile(
        r"RESULT OF ACTION\s+([a-zA-Z0-9_.-]+)\s+\[status=([a-zA-Z0-9_.-]+);\s*reason=([a-zA-Z0-9_.-]+)\]"
    )
    for msg in history:
        content = str(msg.get("content") or "")
        m = pattern.search(content)
        if not m:
            continue
        records.append({"action": m.group(1), "status": m.group(2), "reason": m.group(3)})
    return records


def _count_consecutive_repeats(actions: List[str]) -> int:
    repeats = 0
    for i in range(1, len(actions)):
        if actions[i] == actions[i - 1]:
            repeats += 1
    return repeats


def main() -> None:
    cfg = ConfigManager()
    orch = AgentOrchestrator(cfg)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"diag-californication-{ts}"

    if not orch.get_session_robust(session_id):
        orch.create_session(session_id, interface="web", name="diag-californication-open")

    prompts = [
        "pesquiza a musica californication para min pfvr, quero a url do youtube dela",
        "abre ela no youtube",
        "conseguiu abrir?",
    ]

    turns: List[Dict[str, Any]] = []
    for i, prompt in enumerate(prompts, start=1):
        cap = run_turn(orch, session_id, prompt, timeout_s=300)
        status_codes = []
        for ev in cap.statuses:
            payload = ev.get("payload")
            if isinstance(payload, dict):
                code = payload.get("code")
                if code:
                    status_codes.append(str(code))
        turns.append(
            {
                "turn": i,
                "prompt": prompt,
                "timed_out": cap.timed_out,
                "exception": cap.exception,
                "duration_s": round(cap.ended_at - cap.started_at, 3),
                "status_codes": status_codes,
                "reasoning_tail": cap.reasoning[-4:],
                "responses_tail": cap.responses[-3:],
                "process_return": str(cap.process_return or "")[:500],
            }
        )

    session = orch.get_session_robust(session_id)
    history = session.history if session else []
    action_records = _extract_action_records(history)
    actions = [r["action"] for r in action_records]
    failures = [r for r in action_records if r["status"] == "failure"]
    discovery_actions = [a for a in actions if a.startswith("system.control.skills.")]
    browser_actions = [r for r in action_records if r["action"].startswith("browser.automator.")]
    browser_failures = [r for r in browser_actions if r["status"] == "failure"]
    replan_events = sum(1 for t in turns for c in t["status_codes"] if c == "replan")

    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "session_id": session_id,
        "scenario": prompts,
        "turns": turns,
        "action_trace": action_records,
        "metrics": {
            "total_actions": len(action_records),
            "consecutive_action_repeats": _count_consecutive_repeats(actions),
            "failure_actions": len(failures),
            "replan_events": replan_events,
            "skills_discovery_actions": len(discovery_actions),
            "browser_actions": len(browser_actions),
            "browser_failures": len(browser_failures),
        },
        "bottleneck_hints": {
            "dominant_action": max(set(actions), key=actions.count) if actions else None,
            "most_failed_action": max(set([f["action"] for f in failures]), key=[f["action"] for f in failures].count) if failures else None,
        },
    }

    out_dir = ROOT / "data" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"diag_californication_open_{ts}.json"
    latest = out_dir / "diag_californication_open_latest.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    out_path.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    print(str(out_path))
    print(str(latest))


if __name__ == "__main__":
    main()
