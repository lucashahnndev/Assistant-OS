import datetime
import json
import os
import re
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from config.manager import ConfigManager
from core.orchestrator import AgentOrchestrator


def _approx_tokens(text: str) -> int:
    return max(0, len(text) // 4)


def _extract_action_ids(block: str, known_actions: List[str]) -> List[str]:
    backticked = set(re.findall(r"`([a-zA-Z0-9_.-]+)`", block or ""))
    dotted = set(re.findall(r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,6}\b", block or ""))
    allowed = set(known_actions or [])
    merged = (backticked | dotted) & allowed
    return sorted(merged)


def _build_system_prompt(
    orch: AgentOrchestrator,
    session: Any,
    user_input: str,
    *,
    actions_mode: str,
    include_toon_deltas: bool,
    pretty_toon_state: bool,
) -> str:
    now = datetime.datetime(2026, 2, 25, 18, 0, 0)
    sys_info = {
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "os": "Linux",
        "user": "benchmark",
    }

    allowed_actions = orch._get_allowed_actions_for_session(session)
    cfg = orch.config_manager.config_data
    prompt_ctx = cfg.setdefault("prompt_context", {})
    prev_mode = str(prompt_ctx.get("actions_mode", "on_demand"))
    prompt_ctx["actions_mode"] = actions_mode
    try:
        skills_summary = orch._build_prompt_actions_block(
            user_input=user_input,
            allowed_actions=allowed_actions,
        )
    finally:
        prompt_ctx["actions_mode"] = prev_mode

    toon_state = (
        json.dumps(session.state_summary, ensure_ascii=False, indent=2)
        if pretty_toon_state
        else json.dumps(session.state_summary, ensure_ascii=False, separators=(",", ":"))
    )
    toon_deltas = session.context.get("toon_deltas", []) if include_toon_deltas else []

    return orch.prompt_composer.compose(
        agent_name="Atlas",
        personality="Technical and concise.",
        specialist_prompt="",
        presentation_directive="[PRESENTATION DIRECTIVE]\n- Use markdown when useful.",
        sys_info=sys_info,
        location="Canoas",
        channel="web",
        user_name="benchmark",
        user_language="pt-BR",
        toon_state=toon_state,
        toon_deltas=toon_deltas if isinstance(toon_deltas, list) else [],
        user_input=user_input,
        project_path=str(ROOT),
        workspace_path=str(ROOT),
        venv_python=str(ROOT / "env" / "bin" / "python3"),
        venv_pip=str(ROOT / "env" / "bin" / "pip"),
        browser_pages=[],
        session_summary=session.summary or "",
        scratchpad="",
        attachments=[],
        skills_summary=skills_summary,
        skill_scope="global" if allowed_actions is None else "principal-filtered",
    )


def _latency_ms(fn, rounds: int = 100) -> Dict[str, float]:
    samples = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return {
        "avg": round(float(statistics.mean(samples)), 4),
        "p95": round(float(sorted(samples)[int(rounds * 0.95) - 1]), 4),
        "max": round(float(max(samples)), 4),
    }


def _scenario_eval(
    orch: AgentOrchestrator,
    session: Any,
    *,
    name: str,
    actions_mode: str,
    include_toon_deltas: bool,
    pretty_toon_state: bool,
) -> Dict[str, Any]:
    prompts = [
        "oi",
        "pode me listar suas skills?",
        "detalhe a skill system.control.fs.read",
        "reproduz bohemian rhapsody no youtube",
        "qual foi a primeira musica que pedi para tocar?",
    ]
    target_actions = {
        "pode me listar suas skills?": "system.control.skills.list",
        "detalhe a skill system.control.fs.read": "system.control.skills.describe",
        "reproduz bohemian rhapsody no youtube": "youtube.search.find",
        "qual foi a primeira musica que pedi para tocar?": "memory.recall",
    }

    prompt_rows: List[Dict[str, Any]] = []
    direct_hits = 0
    reachable_hits = 0
    known_actions = orch.skill_registry.list_actions()

    for user_input in prompts:
        prompt = _build_system_prompt(
            orch,
            session,
            user_input,
            actions_mode=actions_mode,
            include_toon_deltas=include_toon_deltas,
            pretty_toon_state=pretty_toon_state,
        )
        actions_block = prompt.split("[AVAILABLE ACTIONS]\n", 1)[-1]
        action_ids = _extract_action_ids(actions_block, known_actions)
        action_set = set(action_ids)
        has_discovery = (
            "system.control.skills.list.ai" in action_set
            and "system.control.skills.describe.ai" in action_set
        )

        target = target_actions.get(user_input)
        direct = bool(target and target in action_set)
        reachable = bool(target and (direct or has_discovery))
        if direct:
            direct_hits += 1
        if reachable:
            reachable_hits += 1

        prompt_rows.append(
            {
                "prompt": user_input,
                "prompt_chars": len(prompt),
                "prompt_tokens_approx": _approx_tokens(prompt),
                "available_action_refs": len(action_set),
                "target_action": target,
                "target_directly_in_prompt": direct,
                "target_reachable_via_discovery": reachable,
            }
        )

    prompt_tokens = [r["prompt_tokens_approx"] for r in prompt_rows]
    prompt_chars = [r["prompt_chars"] for r in prompt_rows]
    action_refs = [r["available_action_refs"] for r in prompt_rows]

    list_ai_fn = lambda: orch.skill_registry.dispatch(
        "system.control.skills.list.ai",
        {"limit": 40, "include_descriptions": False},
        {"allowed_actions": None, "system_driver": orch.system_driver},
    )
    describe_ai_fn = lambda: orch.skill_registry.dispatch(
        "system.control.skills.describe.ai",
        {"action_id": "system.control.fs.read"},
        {"allowed_actions": None, "system_driver": orch.system_driver},
    )

    # For full mode, discovery is not required, but we still measure execution cost for reference.
    discovery_latency = {
        "skills_list_ai_ms": _latency_ms(list_ai_fn, rounds=80),
        "skills_describe_ai_ms": _latency_ms(describe_ai_fn, rounds=80),
    }

    prompt_build_latency = _latency_ms(
        lambda: _build_system_prompt(
            orch,
            session,
            "detalhe a skill system.control.fs.read",
            actions_mode=actions_mode,
            include_toon_deltas=include_toon_deltas,
            pretty_toon_state=pretty_toon_state,
        ),
        rounds=120,
    )

    return {
        "name": name,
        "config": {
            "actions_mode": actions_mode,
            "include_toon_deltas": include_toon_deltas,
            "pretty_toon_state": pretty_toon_state,
        },
        "prompt_stats": {
            "avg_tokens_approx": round(float(statistics.mean(prompt_tokens)), 2),
            "max_tokens_approx": int(max(prompt_tokens)),
            "avg_chars": round(float(statistics.mean(prompt_chars)), 2),
            "avg_available_action_refs": round(float(statistics.mean(action_refs)), 2),
        },
        "latency_ms": {
            "prompt_build": prompt_build_latency,
            "skills_discovery_reference": discovery_latency,
        },
        "comprehension_proxy": {
            "definition": "Proxy based on action reachability in prompt context.",
            "direct_hit_rate": round(direct_hits / max(1, len(target_actions)), 3),
            "reachable_hit_rate": round(reachable_hits / max(1, len(target_actions)), 3),
        },
        "rows": prompt_rows,
    }


def main() -> None:
    cfg = ConfigManager()
    orch = AgentOrchestrator(cfg)
    session_id = "bench-prompt-optimization"
    session = orch.get_session_robust(session_id) or orch.create_session(
        session_id,
        interface="web",
        name="bench-prompt-optimization",
    )
    session.context["user_language"] = "pt-BR"
    session.context["channel"] = "web"
    session.context["user_name"] = "benchmark"
    session.context["toon_deltas"] = [
        {"t": 1700000001, "u": "oi", "a": "reply", "s": "ok", "o": "cumprimento"},
        {"t": 1700000002, "u": "listar skills", "a": "system.control.skills.list.ai", "s": "ok", "o": "40 ações"},
        {"t": 1700000003, "u": "descrever skill", "a": "system.control.skills.describe.ai", "s": "ok", "o": "contrato resumido"},
        {"t": 1700000004, "u": "tocar musica", "a": "youtube.search.find", "s": "ok", "o": "link encontrado"},
    ]

    baseline = _scenario_eval(
        orch,
        session,
        name="baseline_full_injection",
        actions_mode="full",
        include_toon_deltas=False,
        pretty_toon_state=True,
    )
    optimized = _scenario_eval(
        orch,
        session,
        name="optimized_lazy_toon",
        actions_mode="on_demand",
        include_toon_deltas=True,
        pretty_toon_state=False,
    )

    base_avg = baseline["prompt_stats"]["avg_tokens_approx"]
    opt_avg = optimized["prompt_stats"]["avg_tokens_approx"]
    reduction_pct = round(((base_avg - opt_avg) / max(1.0, base_avg)) * 100.0, 2)

    base_prompt_ms = baseline["latency_ms"]["prompt_build"]["avg"]
    opt_prompt_ms = optimized["latency_ms"]["prompt_build"]["avg"]
    prompt_latency_gain_pct = round(((base_prompt_ms - opt_prompt_ms) / max(0.0001, base_prompt_ms)) * 100.0, 2)

    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "scope": "prompt + skills-discovery optimization benchmark",
        "baseline": baseline,
        "optimized": optimized,
        "delta": {
            "avg_prompt_tokens_reduction_pct": reduction_pct,
            "avg_prompt_build_latency_gain_pct": prompt_latency_gain_pct,
            "notes": [
                "Comprehension metrics are proxy-based reachability, not end-to-end semantic accuracy.",
                "Discovery latency is listed as reference since lazy mode may add an extra action round.",
            ],
        },
    }

    diagnostics_dir = ROOT / "data" / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = diagnostics_dir / f"prompt_opt_benchmark_{ts}.json"
    latest = diagnostics_dir / "prompt_opt_benchmark_latest.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    out_path.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    print(str(out_path))
    print(str(latest))


if __name__ == "__main__":
    main()
