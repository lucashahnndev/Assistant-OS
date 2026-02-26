import os
import sys
import json
import time
import threading
import datetime
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(ROOT, "src"))

from core.orchestrator import AgentOrchestrator
from core.identity import PrincipalContext
from config.manager import ConfigManager


def detect_lang(text: str) -> str:
    t = (text or "").lower()
    pt_markers = ["você", "voce", "música", "musica", "toca", "reproduz", "agora", "resumo", "sistema", "qual", "foi", "primeira"]
    en_markers = ["you", "music", "play", "summary", "system", "what", "first"]
    pt = sum(1 for m in pt_markers if m in t)
    en = sum(1 for m in en_markers if m in t)
    if pt >= en:
        return "pt"
    return "en"


def likely_english(text: str) -> bool:
    t = (text or "").lower()
    # Heuristica simples para flag de idioma incorreto
    markers = ["i am", "understood", "task", "error", "could not", "playback", "next step", "please"]
    return any(m in t for m in markers)


def extract_stalled_action(process_return: Any) -> Optional[str]:
    text = str(process_return or "")
    if not text:
        return None

    lowered = text.lower()
    stall_markers = (
        "fiquei travado na ação",
        "travado na acao",
        "stuck on action",
        "without real progress",
        "sem progresso real",
    )
    if not any(marker in lowered for marker in stall_markers):
        return None

    match = re.search(r"'([^']+)'", text)
    if match:
        return match.group(1).strip()
    return "unknown_action"


@dataclass
class TurnCapture:
    prompt: str
    started_at_unix: float = 0.0
    ended_at_unix: float = 0.0
    timed_out: bool = False
    process_return: Any = None
    exception: Optional[str] = None
    statuses: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: List[Dict[str, Any]] = field(default_factory=list)
    responses: List[Dict[str, Any]] = field(default_factory=list)

    def metrics(self) -> Dict[str, Any]:
        t0 = self.started_at_unix
        def rel(ts: float) -> Optional[float]:
            return round(ts - t0, 3) if ts else None

        first_status = self.statuses[0]["ts"] if self.statuses else None
        first_reasoning = self.reasoning[0]["ts"] if self.reasoning else None
        first_response = self.responses[0]["ts"] if self.responses else None
        last_response = self.responses[-1]["text"] if self.responses else ""

        return {
            "latency_first_status_s": rel(first_status),
            "latency_first_reasoning_s": rel(first_reasoning),
            "latency_first_response_s": rel(first_response),
            "total_turn_time_s": round((self.ended_at_unix - self.started_at_unix), 3) if self.ended_at_unix else None,
            "status_events": len(self.statuses),
            "reasoning_events": len(self.reasoning),
            "response_events": len(self.responses),
            "final_response_preview": (last_response or "")[:260],
            "possible_language_mismatch": detect_lang(self.prompt) == "pt" and likely_english(last_response),
        }


def run_turn(orchestrator: AgentOrchestrator, session_id: str, prompt: str, timeout_s: int = 240) -> TurnCapture:
    capture = TurnCapture(prompt=prompt)
    capture.started_at_unix = time.time()

    result_box: Dict[str, Any] = {}

    def send_status(phase, payload=None):
        msg = payload
        if isinstance(payload, dict):
            msg = payload.get("message", payload)
        capture.statuses.append({"ts": time.time(), "phase": phase, "payload": payload, "message": msg})

    def send_reasoning_chunk(content):
        capture.reasoning.append({"ts": time.time(), "content": str(content)})

    def send_response(text, is_chunk=False, attachments=None):
        capture.responses.append({"ts": time.time(), "text": str(text), "is_chunk": bool(is_chunk), "attachments": attachments})

    callbacks = {
        "send_status": send_status,
        "send_reasoning_chunk": send_reasoning_chunk,
        "send_response": send_response,
        "send_complete": lambda: None,
    }

    ctx = PrincipalContext(interface="diagnostic", sender_id="diag_user", sender_name="diagnostic", session_id=session_id)

    def _runner():
        try:
            out = orchestrator.process(
                prompt,
                session_id=session_id,
                callbacks=callbacks,
                context=ctx,
                user_data={}
            )
            result_box["out"] = out
        except Exception as e:
            result_box["exc"] = repr(e)

    th = threading.Thread(target=_runner, daemon=True)
    th.start()
    th.join(timeout=timeout_s)
    if th.is_alive():
        capture.timed_out = True
    capture.ended_at_unix = time.time()
    capture.process_return = result_box.get("out")
    capture.exception = result_box.get("exc")
    return capture


def main():
    cfg = ConfigManager()
    orch = AgentOrchestrator(cfg)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"diag-{ts}"
    # Ensure session exists before processing turns
    if not orch.get_session_robust(session_id):
        orch.create_session(session_id, interface="web", name="diagnostic")

    prompts = [
        "pesquise no wikipedia quem foi ada lovelace e me dê um resumo curto",
        "reproduz californication no youtube",
        "agora toca bohemian rhapsody no youtube",
        "pausa a musica",
        "faça um resumo do status do sistema",
        "qual foi a primeira musica que pedi para tocar?",
    ]

    results: List[Dict[str, Any]] = []

    for i, prompt in enumerate(prompts, start=1):
        cap = run_turn(orch, session_id=session_id, prompt=prompt, timeout_s=240)
        m = cap.metrics()
        process_return = str(cap.process_return) if cap.process_return is not None else ""
        stalled_action = extract_stalled_action(process_return)
        replan_count = sum(
            1
            for status in cap.statuses
            if isinstance(status.get("payload"), dict) and status["payload"].get("code") == "replan"
        )
        results.append({
            "turn": i,
            "prompt": prompt,
            "timed_out": cap.timed_out,
            "exception": cap.exception,
            "process_return": process_return[:400] if process_return else None,
            "stalled_action": stalled_action,
            "replan_count": replan_count,
            "metrics": m,
            "status_tail": cap.statuses[-5:],
            "reasoning_tail": cap.reasoning[-5:],
            "responses_tail": cap.responses[-5:],
        })

    session = orch.get_session_robust(session_id)
    history = session.history if session else []

    # Analise simples automatica
    problems: List[str] = []
    for r in results:
        met = r["metrics"]
        if r["timed_out"]:
            problems.append(f"Turn {r['turn']}: timeout")
        if r.get("exception"):
            problems.append(f"Turn {r['turn']}: exception ({r['exception']})")
        if r.get("stalled_action"):
            problems.append(f"Turn {r['turn']}: stalled action ({r['stalled_action']})")
        if int(r.get("replan_count") or 0) >= 2:
            problems.append(f"Turn {r['turn']}: repeated replanning ({r['replan_count']})")
        if met["latency_first_status_s"] is not None and met["latency_first_status_s"] > 2.0:
            problems.append(f"Turn {r['turn']}: first status latency high ({met['latency_first_status_s']}s)")
        if met["latency_first_response_s"] is not None and met["latency_first_response_s"] > 12.0:
            problems.append(f"Turn {r['turn']}: first response latency high ({met['latency_first_response_s']}s)")
        if met["possible_language_mismatch"]:
            problems.append(f"Turn {r['turn']}: possible language mismatch (PT prompt, EN response)")

    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "session_id": session_id,
        "turn_count": len(results),
        "results": results,
        "history_size": len(history),
        "assistant_messages": sum(1 for h in history if h.get("role") == "assistant"),
        "system_messages": sum(1 for h in history if h.get("role") == "system"),
        "problems_detected": problems,
    }

    out_dir = os.path.join(ROOT, "data", "diagnostics")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"diag_report_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(out_path)


if __name__ == "__main__":
    main()
