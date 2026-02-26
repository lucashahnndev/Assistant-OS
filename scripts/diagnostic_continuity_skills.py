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
    process_return: Any = None
    exception: Optional[str] = None
    timed_out: bool = False
    statuses: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: List[Dict[str, Any]] = field(default_factory=list)
    responses: List[Dict[str, Any]] = field(default_factory=list)
    t0: float = 0.0
    t1: float = 0.0


def run_turn(orch: AgentOrchestrator, session_id: str, prompt: str, timeout_s: int = 180) -> TurnCapture:
    cap = TurnCapture(prompt=prompt, t0=time.time())
    box: Dict[str, Any] = {}

    def send_status(phase, payload=None):
        cap.statuses.append({"ts": time.time(), "phase": phase, "payload": payload})

    def send_reasoning_chunk(content):
        cap.reasoning.append({"ts": time.time(), "content": str(content)})

    def send_response(text, is_chunk=False, attachments=None):
        cap.responses.append({"ts": time.time(), "text": str(text), "is_chunk": bool(is_chunk), "attachments": attachments})

    callbacks = {
        "send_status": send_status,
        "send_reasoning_chunk": send_reasoning_chunk,
        "send_response": send_response,
        "send_complete": lambda: None,
    }
    ctx = PrincipalContext(interface="diagnostic", sender_id="diag", sender_name="diag", session_id=session_id)

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
    cap.t1 = time.time()
    cap.process_return = box.get("out")
    cap.exception = box.get("exc")
    return cap


def _extract_action_from_json_text(text: str) -> Optional[str]:
    try:
        payload = json.loads(text)
    except Exception:
        return None
    if isinstance(payload, dict):
        action = payload.get("action")
        if isinstance(action, str) and action.strip():
            return action.strip()
    return None


def main() -> None:
    cfg = ConfigManager()
    orch = AgentOrchestrator(cfg)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"diag-continuity-{ts}"
    if not orch.get_session_robust(session_id):
        orch.create_session(session_id, interface="web", name="diag-continuity-skills")

    prompts = [
        "pesquiza a musica californication para min pfvr, quero a url do youtube dela",
        "conseguiu?",
        "então me passa a url da bohemian rhapsody no youtube",
        "qual foi a primeira música que eu pedi?",
    ]

    turns: List[Dict[str, Any]] = []
    for idx, prompt in enumerate(prompts, start=1):
        cap = run_turn(orch, session_id=session_id, prompt=prompt, timeout_s=240)
        turns.append(
            {
                "turn": idx,
                "prompt": prompt,
                "timed_out": cap.timed_out,
                "exception": cap.exception,
                "duration_s": round(cap.t1 - cap.t0, 3),
                "responses_tail": cap.responses[-3:],
                "status_tail": cap.statuses[-5:],
                "process_return": str(cap.process_return or "")[:300],
            }
        )

    session = orch.get_session_robust(session_id)
    history = session.history if session else []
    reasoning_actions: List[str] = []
    for msg in history:
        if msg.get("role") in {"assistant", "system"}:
            action = _extract_action_from_json_text(str(msg.get("content") or ""))
            if action:
                reasoning_actions.append(action)

    skill_list_calls = [a for a in reasoning_actions if a == "system.control.skills.list.ai"]
    consecutive_skill_list = 0
    for i in range(1, len(reasoning_actions)):
        if reasoning_actions[i] == "system.control.skills.list.ai" and reasoning_actions[i - 1] == "system.control.skills.list.ai":
            consecutive_skill_list += 1

    non_json_responses = 0
    for msg in history:
        if msg.get("role") != "assistant":
            continue
        content = str(msg.get("content") or "")
        if content.startswith("{") and content.endswith("}"):
            continue
        # natural-language assistant replies in middle of loops
        if re.search(r"vou pesquisar|estou|aguarde|já iniciei|tentar novamente", content.lower()):
            non_json_responses += 1

    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "session_id": session_id,
        "turns": turns,
        "history_size": len(history),
        "reasoning_actions": reasoning_actions[-30:],
        "metrics": {
            "skills_list_ai_calls": len(skill_list_calls),
            "consecutive_skills_list_ai_pairs": consecutive_skill_list,
            "loopy_natural_language_assistant_msgs": non_json_responses,
        },
    }

    out_dir = ROOT / "data" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"diag_continuity_skills_{ts}.json"
    latest = out_dir / "diag_continuity_skills_latest.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    out_path.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    print(str(out_path))
    print(str(latest))


if __name__ == "__main__":
    main()
