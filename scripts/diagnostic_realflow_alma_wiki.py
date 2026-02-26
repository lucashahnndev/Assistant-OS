import datetime
import json
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


def run_turn(orch: AgentOrchestrator, session_id: str, prompt: str, timeout_s: int = 300) -> TurnCapture:
    cap = TurnCapture(prompt=prompt, started_at=time.time())
    box: Dict[str, Any] = {}

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
            box["out"] = orch.process(prompt, session_id=session_id, callbacks=callbacks, context=ctx, user_data={})
        except Exception as exc:
            box["exc"] = repr(exc)

    th = threading.Thread(target=_runner, daemon=True)
    th.start()
    th.join(timeout=timeout_s)
    if th.is_alive():
        cap.timed_out = True
    cap.ended_at = time.time()
    cap.process_return = box.get("out")
    cap.exception = box.get("exc")
    return cap


def extract_action_records(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    pattern = re.compile(
        r"RESULT OF ACTION\s+([a-zA-Z0-9_.-]+)\s+\[status=([a-zA-Z0-9_.-]+);\s*reason=([a-zA-Z0-9_.-]+)\]"
    )
    out: List[Dict[str, str]] = []
    for msg in history:
        content = str(msg.get("content") or "")
        m = pattern.search(content)
        if not m:
            continue
        out.append({"action": m.group(1), "status": m.group(2), "reason": m.group(3)})
    return out


def consecutive_repeats(actions: List[str]) -> int:
    repeats = 0
    for i in range(1, len(actions)):
        if actions[i] == actions[i - 1]:
            repeats += 1
    return repeats


def has_youtube_url(text: str) -> bool:
    lowered = str(text or "").lower()
    return "youtube.com/watch" in lowered or "youtu.be/" in lowered


def has_wiki_summary_signal(text: str) -> bool:
    lowered = str(text or "").lower()
    # Weak semantic signal for "foguetes + resumo"
    return (
        ("foguet" in lowered or "rocket" in lowered)
        and ("resumo" in lowered or "summary" in lowered or len(lowered) > 120)
    )


def main() -> None:
    cfg = ConfigManager()
    orch = AgentOrchestrator(cfg)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"diag-realflow-{ts}"
    if not orch.get_session_robust(session_id):
        orch.create_session(session_id, interface="web", name="diag-realflow-alma-wiki")

    prompts = [
        "pesquisa a musica alma no youtube do cantor tz da coro",
        "pesquisa sobre foguetes na wikipedia e forneça um resumo",
    ]

    turns: List[Dict[str, Any]] = []
    for idx, prompt in enumerate(prompts, start=1):
        cap = run_turn(orch, session_id=session_id, prompt=prompt, timeout_s=300)
        turn_text = "\n".join([str(r.get("text") or "") for r in cap.responses])
        turns.append(
            {
                "turn": idx,
                "prompt": prompt,
                "timed_out": cap.timed_out,
                "exception": cap.exception,
                "duration_s": round(cap.ended_at - cap.started_at, 3),
                "status_count": len(cap.statuses),
                "reasoning_count": len(cap.reasoning),
                "response_count": len(cap.responses),
                "replan_events": sum(
                    1
                    for st in cap.statuses
                    if isinstance(st.get("payload"), dict) and st["payload"].get("code") == "replan"
                ),
                "responses_tail": cap.responses[-4:],
                "process_return": str(cap.process_return or "")[:500],
                "task_signals": {
                    "contains_youtube_url": has_youtube_url(turn_text),
                    "contains_wiki_summary_signal": has_wiki_summary_signal(turn_text),
                },
            }
        )

    session = orch.get_session_robust(session_id)
    history = session.history if session else []
    action_records = extract_action_records(history)
    actions = [r["action"] for r in action_records]
    failures = [r for r in action_records if r["status"] == "failure"]

    skills_discovery = [a for a in actions if a.startswith("system.control.skills.")]
    youtube_actions = [a for a in actions if a.startswith("youtube.")]
    wiki_actions = [a for a in actions if a.startswith("wikipedia.")]

    problems: List[str] = []
    for t in turns:
        if t["timed_out"]:
            problems.append(f"turn_{t['turn']}: timeout")
        if t["exception"]:
            problems.append(f"turn_{t['turn']}: exception={t['exception']}")
        if t["replan_events"] >= 2:
            problems.append(f"turn_{t['turn']}: repeated_replan={t['replan_events']}")
    if consecutive_repeats(actions) >= 2:
        problems.append(f"action_loop: consecutive_repeats={consecutive_repeats(actions)}")
    if len(skills_discovery) >= 3:
        problems.append(f"over_discovery: skills_discovery_calls={len(skills_discovery)}")
    if not turns[0]["task_signals"]["contains_youtube_url"]:
        problems.append("task1_not_fulfilled: missing_youtube_url")
    if not turns[1]["task_signals"]["contains_wiki_summary_signal"]:
        problems.append("task2_not_fulfilled: missing_wikipedia_summary_signal")

    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "session_id": session_id,
        "scenario": prompts,
        "turns": turns,
        "history_size": len(history),
        "action_trace": action_records,
        "metrics": {
            "total_actions": len(actions),
            "consecutive_action_repeats": consecutive_repeats(actions),
            "failure_actions": len(failures),
            "skills_discovery_actions": len(skills_discovery),
            "youtube_actions": len(youtube_actions),
            "wikipedia_actions": len(wiki_actions),
        },
        "problems_detected": problems,
    }

    out_dir = ROOT / "data" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"diag_realflow_alma_wiki_{ts}.json"
    latest = out_dir / "diag_realflow_alma_wiki_latest.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    out_path.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    print(str(out_path))
    print(str(latest))


if __name__ == "__main__":
    main()
