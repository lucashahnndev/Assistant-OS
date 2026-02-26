import datetime
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List

# Local imports
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from config.manager import ConfigManager
from core.orchestrator import AgentOrchestrator
from core.session import Session
from services.memory.memory_service import MemoryService
from services.memory.episodic_memory import EpisodicMemoryService
from services.memory.scratchpad_service import ScratchpadService


def _safe_count(collection: Any) -> int:
    try:
        return int(collection.count()) if collection else 0
    except Exception:
        return 0


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            fp = Path(root) / name
            try:
                total += fp.stat().st_size
            except FileNotFoundError:
                continue
    return total


def _gather_sessions_stats(sessions_dir: Path) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    if not sessions_dir.exists():
        return {"count": 0, "rows": []}

    for sid in sorted(os.listdir(sessions_dir)):
        session_json = sessions_dir / sid / "session.json"
        scratchpad_md = sessions_dir / sid / "scratchpad.md"
        if not session_json.exists():
            continue
        try:
            payload = json.loads(session_json.read_text(encoding="utf-8"))
        except Exception:
            continue

        history = payload.get("history") or []
        rows.append(
            {
                "session_id": sid,
                "history_messages": len(history),
                "history_tokens": sum(int(m.get("tokens", 0)) for m in history if isinstance(m, dict)),
                "summary_len_chars": len(str(payload.get("summary") or "")),
                "state_summary_len_chars": len(json.dumps(payload.get("state_summary") or {}, ensure_ascii=False)),
                "scratchpad_len_chars": len(scratchpad_md.read_text(encoding="utf-8")) if scratchpad_md.exists() else 0,
            }
        )

    history_tokens = [r["history_tokens"] for r in rows]
    summary_lens = [r["summary_len_chars"] for r in rows]
    scratchpad_lens = [r["scratchpad_len_chars"] for r in rows]
    state_summary_lens = [r["state_summary_len_chars"] for r in rows]

    def _stats(values: List[int]) -> Dict[str, float]:
        if not values:
            return {"avg": 0, "p95": 0, "max": 0}
        sorted_vals = sorted(values)
        p95_idx = max(0, int(len(sorted_vals) * 0.95) - 1)
        return {
            "avg": round(float(statistics.mean(values)), 2),
            "p95": float(sorted_vals[p95_idx]),
            "max": float(max(values)),
        }

    top_sessions = sorted(rows, key=lambda r: r["history_tokens"], reverse=True)[:10]

    return {
        "count": len(rows),
        "history_tokens": _stats(history_tokens),
        "summary_len_chars": _stats(summary_lens),
        "scratchpad_len_chars": _stats(scratchpad_lens),
        "state_summary_len_chars": _stats(state_summary_lens),
        "top_sessions_by_history_tokens": top_sessions,
    }


def _benchmark_recall_latency(ms: MemoryService, em: EpisodicMemoryService) -> Dict[str, Any]:
    samples = [
        "user preferences",
        "last failed action",
        "music request",
        "system status",
        "task summary",
    ]

    semantic_lat = []
    episodic_lat = []
    for query in samples:
        t0 = time.perf_counter()
        _ = ms.search_memory(query, n_results=5)
        semantic_lat.append((time.perf_counter() - t0) * 1000.0)

        t0 = time.perf_counter()
        _ = em.recall_episodes(query, n_results=3)
        episodic_lat.append((time.perf_counter() - t0) * 1000.0)

    return {
        "queries": samples,
        "semantic_search_ms": {
            "avg": round(float(statistics.mean(semantic_lat)), 3) if semantic_lat else 0,
            "max": round(float(max(semantic_lat)), 3) if semantic_lat else 0,
        },
        "episodic_recall_ms": {
            "avg": round(float(statistics.mean(episodic_lat)), 3) if episodic_lat else 0,
            "max": round(float(max(episodic_lat)), 3) if episodic_lat else 0,
        },
    }


def _prompt_memory_footprint(orch: AgentOrchestrator, session_id: str = "bench-memory-freeze") -> Dict[str, Any]:
    session = orch.get_session_robust(session_id)
    if not session:
        session = orch.create_session(session_id, interface="web", name="bench-memory-freeze")

    session.context.update({"user_language": "pt-BR", "channel": "web", "user_name": "benchmark"})
    prompt = orch._construct_system_prompt(session, user_input="continue")

    def _block_size(header: str, next_headers: List[str]) -> int:
        start = prompt.find(header)
        if start < 0:
            return 0
        end = len(prompt)
        for h in next_headers:
            idx = prompt.find(h, start + 1)
            if idx != -1 and idx < end:
                end = idx
        return end - start

    headers = [
        "[INTERNAL STATE (TOON)]",
        "[CONSOLIDATED SESSION SUMMARY]",
        "[PERSISTENT SCRATCHPAD]",
        "[AVAILABLE ACTIONS]",
        "[STRUCTURED OUTPUT CONTRACT]",
    ]
    sizes = {}
    for i, h in enumerate(headers):
        sizes[h] = _block_size(h, headers[i + 1 :])

    return {
        "prompt_chars": len(prompt),
        "prompt_tokens_approx": len(prompt) // 4,
        "block_sizes_chars": sizes,
    }


def main() -> None:
    cfg = ConfigManager()
    orch = AgentOrchestrator(cfg)
    ms = MemoryService()
    em = EpisodicMemoryService()
    ss = ScratchpadService(orch.workspace_service)

    sessions_dir = Path(orch.sessions_dir)
    data_memory_dir = ROOT / "data" / "memory"
    diagnostics_dir = ROOT / "data" / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "report_type": "memory_freeze_baseline",
        "cognitive_memory": {
            "semantic_factual_items": _safe_count(ms.collection),
            "episodic_items": _safe_count(em.collection),
            "semantic_store_size_bytes": _dir_size_bytes(data_memory_dir / "chroma"),
            "episodic_store_size_bytes": _dir_size_bytes(data_memory_dir / "chroma_episodic"),
        },
        "sessions_memory": _gather_sessions_stats(sessions_dir),
        "recall_latency": _benchmark_recall_latency(ms, em),
        "prompt_memory_footprint": _prompt_memory_footprint(orch),
        "scratchpad_global_fallback_len_chars": len(ss.read(None)),
    }

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = diagnostics_dir / f"memory_freeze_{ts}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    latest = diagnostics_dir / "memory_freeze_latest.json"
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(out_path))
    print(str(latest))


if __name__ == "__main__":
    main()
