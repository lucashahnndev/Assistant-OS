import datetime
import json
from pathlib import Path
from typing import Any, Dict

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from config.manager import ConfigManager
from core.orchestrator import AgentOrchestrator
from utils.toon_codec import dumps_toon, encode_reasoning_step, encode_state_summary


def _tok(s: str) -> int:
    return max(0, len(str(s or "")) // 4)


def _pct(old: int, new: int) -> float:
    if old <= 0:
        return 0.0
    return round(((old - new) / old) * 100.0, 2)


def _prompt_before_after(orch: AgentOrchestrator, session: Any, user_input: str) -> Dict[str, Any]:
    cfg = orch.config_manager.config_data.setdefault("prompt_context", {})
    prev = str(cfg.get("state_summary_mode", "toon"))
    try:
        cfg["state_summary_mode"] = "legacy"
        prompt_legacy = orch._construct_system_prompt(session, user_input=user_input)
        cfg["state_summary_mode"] = "toon"
        prompt_toon = orch._construct_system_prompt(session, user_input=user_input)
    finally:
        cfg["state_summary_mode"] = prev

    old = _tok(prompt_legacy)
    new = _tok(prompt_toon)
    return {
        "legacy_tokens_approx": old,
        "toon_tokens_approx": new,
        "reduction_pct": _pct(old, new),
    }


def _state_summary_before_after(session: Any) -> Dict[str, Any]:
    legacy = json.dumps(session.state_summary, ensure_ascii=False, separators=(",", ":"))
    toon = dumps_toon(encode_state_summary(session.state_summary))
    old = _tok(legacy)
    new = _tok(toon)
    return {
        "legacy_tokens_approx": old,
        "toon_tokens_approx": new,
        "reduction_pct": _pct(old, new),
        "legacy_chars": len(legacy),
        "toon_chars": len(toon),
    }


def _reasoning_entry_before_after() -> Dict[str, Any]:
    payload = {
        "thought": "Vou pesquisar sobre foguetes na wikipedia e fornecer um resumo curto com fonte confiável.",
        "plan": ["[x] entender pedido", "[/] buscar na wikipedia", "[ ] resumir e responder"],
        "action": "wikipedia.search",
        "params": {"query": "foguetes", "limit": 5},
    }
    legacy = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    toon = dumps_toon(
        encode_reasoning_step(
            thought=payload["thought"],
            plan=payload["plan"],
            action=payload["action"],
            params=payload["params"],
        )
    )
    old = _tok(legacy)
    new = _tok(toon)
    return {
        "legacy_tokens_approx": old,
        "toon_tokens_approx": new,
        "reduction_pct": _pct(old, new),
        "legacy_chars": len(legacy),
        "toon_chars": len(toon),
    }


def _dynamic_blocks_before_after() -> Dict[str, Any]:
    browser_pages = [
        {"title": "Wikipedia - Foguete", "url": "https://pt.wikipedia.org/wiki/Foguete_espacial", "status": "ready"},
        {"title": "YouTube", "url": "https://www.youtube.com/watch?v=SEomzWa9PHU", "status": "ready"},
    ]
    attachments = [
        {"type": "image", "path": "/tmp/screenshot.png", "mime": "image/png"},
        {"type": "doc", "path": "/tmp/brief.txt", "mime": "text/plain"},
    ]
    legacy_browser = json.dumps(browser_pages, ensure_ascii=False, indent=2)
    toon_browser = json.dumps(browser_pages, ensure_ascii=False, separators=(",", ":"))
    legacy_attach = json.dumps(attachments, ensure_ascii=False, indent=2)
    toon_attach = json.dumps(attachments, ensure_ascii=False, separators=(",", ":"))

    old = _tok(legacy_browser + legacy_attach)
    new = _tok(toon_browser + toon_attach)
    return {
        "legacy_tokens_approx": old,
        "toon_tokens_approx": new,
        "reduction_pct": _pct(old, new),
    }


def main() -> None:
    cfg = ConfigManager()
    orch = AgentOrchestrator(cfg)
    session_id = "bench-json-toon-migration"
    session = orch.get_session_robust(session_id) or orch.create_session(
        session_id,
        interface="web",
        name="bench-json-toon-migration",
    )
    session.context["user_language"] = "pt-BR"
    session.context["channel"] = "web"
    session.context["user_name"] = "benchmark"
    session.state_summary.update(
        {
            "goal": "Pesquisar e resumir",
            "cursor": "2/4 (step: wikipedia.search)",
            "done_steps": ["entender pedido"],
            "last_outcome": "Resultado da wikipedia retornado com sucesso",
            "last_error": "None",
            "retry_count": 0,
        }
    )

    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "scope": "JSON->TOON migration benchmark",
        "sections": {
            "state_summary": _state_summary_before_after(session),
            "reasoning_entry": _reasoning_entry_before_after(),
            "dynamic_blocks": _dynamic_blocks_before_after(),
            "prompt": _prompt_before_after(
                orch,
                session,
                "pesquisa sobre foguetes na wikipedia e forneça um resumo",
            ),
        },
    }

    out_dir = ROOT / "data" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"json_to_toon_benchmark_{ts}.json"
    latest = out_dir / "json_to_toon_benchmark_latest.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    out_path.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    print(str(out_path))
    print(str(latest))


if __name__ == "__main__":
    main()
