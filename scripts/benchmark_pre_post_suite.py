import datetime
import json
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
from skills.system_control.skill import SystemSkill


def _approx_tokens(text: str) -> int:
    return max(0, len(text) // 4)


def _extract_action_ids(block: str, known_actions: List[str]) -> List[str]:
    backticked = set(re.findall(r"`([a-zA-Z0-9_.-]+)`", block or ""))
    dotted = set(re.findall(r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,6}\b", block or ""))
    allowed = set(known_actions or [])
    merged = (backticked | dotted) & allowed
    return sorted(merged)


def _latency_ms(fn, rounds: int = 80) -> Dict[str, float]:
    samples: List[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    ordered = sorted(samples)
    p95_idx = max(0, int(len(ordered) * 0.95) - 1)
    return {
        "avg": round(float(statistics.mean(samples)), 4),
        "p95": round(float(ordered[p95_idx]), 4),
        "max": round(float(max(samples)), 4),
    }


def _build_prompt(
    orch: AgentOrchestrator,
    session: Any,
    user_input: str,
    *,
    actions_mode: str,
    include_toon_deltas: bool,
    pretty_toon_state: bool,
) -> str:
    now = datetime.datetime(2026, 2, 25, 20, 15, 0)
    sys_info = {
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "os": "Linux",
        "user": "benchmark",
    }

    allowed_actions = orch._get_allowed_actions_for_session(session)
    prompt_cfg = orch.config_manager.config_data.setdefault("prompt_context", {})
    prev_mode = str(prompt_cfg.get("actions_mode", "on_demand"))
    prompt_cfg["actions_mode"] = actions_mode
    try:
        skills_summary = orch._build_prompt_actions_block(user_input=user_input, allowed_actions=allowed_actions)
    finally:
        prompt_cfg["actions_mode"] = prev_mode

    toon_state = (
        json.dumps(session.state_summary, ensure_ascii=False, indent=2)
        if pretty_toon_state
        else json.dumps(session.state_summary, ensure_ascii=False, separators=(",", ":"))
    )
    toon_deltas_raw = session.context.get("toon_deltas", []) if include_toon_deltas else []
    toon_deltas = toon_deltas_raw if isinstance(toon_deltas_raw, list) else []

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
        toon_deltas=toon_deltas,
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


def _prompt_pre_post(orch: AgentOrchestrator, session: Any) -> Dict[str, Any]:
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

    def run_case(actions_mode: str, include_toon_deltas: bool, pretty_toon_state: bool) -> Dict[str, Any]:
        known_actions = orch.skill_registry.list_actions()
        rows: List[Dict[str, Any]] = []
        direct_hits = 0
        reachable_hits = 0
        for prompt in prompts:
            full_prompt = _build_prompt(
                orch,
                session,
                prompt,
                actions_mode=actions_mode,
                include_toon_deltas=include_toon_deltas,
                pretty_toon_state=pretty_toon_state,
            )
            action_block = full_prompt.split("[AVAILABLE ACTIONS]\n", 1)[-1]
            actions = set(_extract_action_ids(action_block, known_actions))
            has_discovery = (
                "system.control.skills.list.ai" in actions
                and "system.control.skills.describe.ai" in actions
            )
            target = target_actions.get(prompt)
            direct = bool(target and target in actions)
            reachable = bool(target and (direct or has_discovery))
            if direct:
                direct_hits += 1
            if reachable:
                reachable_hits += 1
            rows.append(
                {
                    "prompt": prompt,
                    "prompt_tokens_approx": _approx_tokens(full_prompt),
                    "prompt_chars": len(full_prompt),
                    "action_refs": len(actions),
                    "direct_hit": direct,
                    "reachable_hit": reachable,
                }
            )

        build_latency = _latency_ms(
            lambda: _build_prompt(
                orch,
                session,
                "detalhe a skill system.control.fs.read",
                actions_mode=actions_mode,
                include_toon_deltas=include_toon_deltas,
                pretty_toon_state=pretty_toon_state,
            ),
            rounds=120,
        )

        tok = [r["prompt_tokens_approx"] for r in rows]
        chars = [r["prompt_chars"] for r in rows]
        refs = [r["action_refs"] for r in rows]
        return {
            "rows": rows,
            "avg_prompt_tokens_approx": round(float(statistics.mean(tok)), 2),
            "avg_prompt_chars": round(float(statistics.mean(chars)), 2),
            "avg_action_refs": round(float(statistics.mean(refs)), 2),
            "build_latency_ms": build_latency,
            "direct_hit_rate": round(direct_hits / max(1, len(target_actions)), 3),
            "reachable_hit_rate": round(reachable_hits / max(1, len(target_actions)), 3),
        }

    baseline = run_case("full", include_toon_deltas=False, pretty_toon_state=True)
    optimized = run_case("on_demand", include_toon_deltas=True, pretty_toon_state=False)
    base_tok = baseline["avg_prompt_tokens_approx"]
    opt_tok = optimized["avg_prompt_tokens_approx"]
    base_lat = baseline["build_latency_ms"]["avg"]
    opt_lat = optimized["build_latency_ms"]["avg"]
    return {
        "baseline": baseline,
        "optimized": optimized,
        "delta": {
            "prompt_tokens_reduction_pct": round(((base_tok - opt_tok) / max(1.0, base_tok)) * 100.0, 2),
            "prompt_build_latency_gain_pct": round(((base_lat - opt_lat) / max(0.0001, base_lat)) * 100.0, 2),
        },
    }


def _skills_payload_pre_post(orch: AgentOrchestrator) -> Dict[str, Any]:
    system_skill = SystemSkill(kernel=type("K", (), {"orchestrator": orch})(), config={})
    context = {"allowed_actions": None, "system_driver": orch.system_driver}

    def run_list_legacy():
        return system_skill.execute(
            "system.control.skills.list",
            {"format": "legacy", "limit": 40, "include_descriptions": True},
            context,
        )

    def run_list_toon():
        return system_skill.execute(
            "system.control.skills.list.ai",
            {"format": "toon", "limit": 40, "include_descriptions": False},
            context,
        )

    def run_desc_legacy():
        return system_skill.execute(
            "system.control.skills.describe",
            {"format": "legacy", "action_id": "system.control.fs.read"},
            context,
        )

    def run_desc_toon():
        return system_skill.execute(
            "system.control.skills.describe.ai",
            {"format": "toon", "action_id": "system.control.fs.read"},
            context,
        )

    list_legacy = run_list_legacy()
    list_toon = run_list_toon()
    desc_legacy = run_desc_legacy()
    desc_toon = run_desc_toon()

    list_legacy_s = json.dumps(list_legacy, ensure_ascii=False)
    list_toon_s = json.dumps(list_toon, ensure_ascii=False)
    desc_legacy_s = json.dumps(desc_legacy, ensure_ascii=False)
    desc_toon_s = json.dumps(desc_toon, ensure_ascii=False)

    return {
        "legacy": {
            "list_tokens_approx": _approx_tokens(list_legacy_s),
            "describe_tokens_approx": _approx_tokens(desc_legacy_s),
        },
        "toon": {
            "list_tokens_approx": _approx_tokens(list_toon_s),
            "describe_tokens_approx": _approx_tokens(desc_toon_s),
            "list_exec_ms": _latency_ms(run_list_toon, rounds=120),
            "describe_exec_ms": _latency_ms(run_desc_toon, rounds=120),
        },
        "delta": {
            "list_reduction_pct": round(
                ((_approx_tokens(list_legacy_s) - _approx_tokens(list_toon_s)) / max(1, _approx_tokens(list_legacy_s))) * 100.0,
                2,
            ),
            "describe_reduction_pct": round(
                ((_approx_tokens(desc_legacy_s) - _approx_tokens(desc_toon_s)) / max(1, _approx_tokens(desc_legacy_s))) * 100.0,
                2,
            ),
        },
    }


def _memory_context_pre_post(orch: AgentOrchestrator, session: Any) -> Dict[str, Any]:
    session.context["toon_deltas"] = [
        {"t": 1700000001, "u": "oi", "a": "reply", "s": "ok", "o": "cumprimento"},
        {"t": 1700000002, "u": "listar skills", "a": "system.control.skills.list.ai", "s": "ok", "o": "40 ações"},
        {"t": 1700000003, "u": "descrever skill", "a": "system.control.skills.describe.ai", "s": "ok", "o": "contrato resumido"},
    ]
    prompt_cfg = orch.config_manager.config_data.setdefault("prompt_context", {})
    prev_mode = str(prompt_cfg.get("toon_deltas_mode", "adaptive"))

    prompt_cfg["toon_deltas_mode"] = "always"
    forced_simple = orch._construct_system_prompt(session, user_input="oi")
    forced_followup = orch._construct_system_prompt(session, user_input="conseguiu abrir ela?")

    prompt_cfg["toon_deltas_mode"] = "adaptive"
    adaptive_simple = orch._construct_system_prompt(session, user_input="oi")
    adaptive_followup = orch._construct_system_prompt(session, user_input="conseguiu abrir ela?")

    prompt_cfg["toon_deltas_mode"] = prev_mode

    old_tokens = _approx_tokens(forced_simple)
    new_tokens = _approx_tokens(adaptive_simple)
    return {
        "forced_deltas_simple_tokens_approx": old_tokens,
        "adaptive_deltas_simple_tokens_approx": new_tokens,
        "simple_turn_reduction_pct": round(((old_tokens - new_tokens) / max(1, old_tokens)) * 100.0, 2),
        "forced_deltas_followup_tokens_approx": _approx_tokens(forced_followup),
        "adaptive_deltas_followup_tokens_approx": _approx_tokens(adaptive_followup),
        "notes": [
            "Adaptive mode should suppress deltas on simple turns and keep them on follow-up turns."
        ],
    }


def _specialist_prompt_pre_post(orch: AgentOrchestrator, session: Any) -> Dict[str, Any]:
    prompt_cfg = orch.config_manager.config_data.setdefault("prompt_context", {})
    prev_mode = str(prompt_cfg.get("specialist_prompt_mode", "compact"))
    prev_max = int(prompt_cfg.get("specialist_prompt_max_chars", 320) or 320)
    prev_specialist = str(session.context.get("active_specialist", "") or "")

    session.context["active_specialist"] = "web_expert"
    prompt_cfg["specialist_prompt_max_chars"] = 320

    prompt_cfg["specialist_prompt_mode"] = "raw"
    raw_prompt = orch._construct_system_prompt(session, user_input="analise essa pagina e extraia dados")

    prompt_cfg["specialist_prompt_mode"] = "compact"
    compact_prompt = orch._construct_system_prompt(session, user_input="analise essa pagina e extraia dados")
    prompt_cfg["specialist_prompt_mode"] = "ultra_compact"
    ultra_prompt = orch._construct_system_prompt(session, user_input="analise essa pagina e extraia dados")

    prompt_cfg["specialist_prompt_mode"] = prev_mode
    prompt_cfg["specialist_prompt_max_chars"] = prev_max
    session.context["active_specialist"] = prev_specialist

    raw_tokens = _approx_tokens(raw_prompt)
    compact_tokens = _approx_tokens(compact_prompt)
    ultra_tokens = _approx_tokens(ultra_prompt)
    return {
        "raw_tokens_approx": raw_tokens,
        "compact_tokens_approx": compact_tokens,
        "ultra_compact_tokens_approx": ultra_tokens,
        "compact_reduction_pct": round(((raw_tokens - compact_tokens) / max(1, raw_tokens)) * 100.0, 2),
        "ultra_reduction_pct": round(((raw_tokens - ultra_tokens) / max(1, raw_tokens)) * 100.0, 2),
    }


def _observation_compaction_pre_post(orch: AgentOrchestrator) -> Dict[str, Any]:
    # Synthetic long structured tool result representative of web/search payloads.
    payload = {
        "ok": True,
        "status": "success",
        "items": [{"id": i, "title": f"Item {i}", "text": "x" * 120} for i in range(60)],
        "meta": {"provider": "synthetic", "query": "californication url youtube"},
    }

    raw = json.dumps(payload, ensure_ascii=False)
    legacy_trunc = raw[:2000] + "..." if len(raw) > 2000 else raw
    legacy_obs = (
        "RESULT OF ACTION web.search.discover "
        f"[status=success; reason=success]: {legacy_trunc}"
    )

    limits = orch._observation_limits()
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    compact_trunc = compact[: limits["max_chars"]] + "..." if len(compact) > limits["max_chars"] else compact
    compact_obs = (
        "RESULT OF ACTION web.search.discover "
        f"[status=success; reason=success]: {compact_trunc}"
    )

    legacy_tokens = _approx_tokens(legacy_obs)
    compact_tokens = _approx_tokens(compact_obs)
    return {
        "legacy_observation_tokens_approx": legacy_tokens,
        "compact_observation_tokens_approx": compact_tokens,
        "reduction_pct": round(((legacy_tokens - compact_tokens) / max(1, legacy_tokens)) * 100.0, 2),
        "observation_max_chars": limits["max_chars"],
    }


def main() -> None:
    cfg = ConfigManager()
    orch = AgentOrchestrator(cfg)
    session_id = "bench-pre-post-suite"
    session = orch.get_session_robust(session_id) or orch.create_session(
        session_id,
        interface="web",
        name="bench-pre-post-suite",
    )
    session.context["user_language"] = "pt-BR"
    session.context["channel"] = "web"
    session.context["user_name"] = "benchmark"

    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "scope": "pre-post suite (prompt, skills payload, memory context)",
        "prompt": _prompt_pre_post(orch, session),
        "skills_payload": _skills_payload_pre_post(orch),
        "memory_context": _memory_context_pre_post(orch, session),
        "specialist_context": _specialist_prompt_pre_post(orch, session),
        "observation_context": _observation_compaction_pre_post(orch),
        "notes": [
            "Benchmarks are local deterministic measurements (prompt construction and skill payload shape).",
            "External provider latency/availability is excluded from this suite.",
        ],
    }

    out_dir = ROOT / "data" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"pre_post_suite_{ts}.json"
    latest = out_dir / "pre_post_suite_latest.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    out_path.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    print(str(out_path))
    print(str(latest))


if __name__ == "__main__":
    main()
