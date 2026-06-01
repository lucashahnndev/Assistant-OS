from fastapi import APIRouter, Depends, HTTPException, Request, File, UploadFile
from fastapi.responses import StreamingResponse, FileResponse, Response
from core.identity import PrincipalContext
from capabilities.weather_control.capability import WeatherCapability
from ..auth import get_current_user
from ..core.models import User, AuditLog
from ..core.database import get_db
from sqlalchemy.orm import Session
import logging
import json
import os
import re
import shutil
import subprocess
import time

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
logger = logging.getLogger("SessionsRoutes")
_NET_RATE_SAMPLES = {}
_WEATHER_CITY_PATTERNS = [
    re.compile(r"\b(?:clima|tempo|weather|forecast|previs[aã]o)[^.\n]{0,90}?\b(?:em|para|in|for)\s+([a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ0-9\s,\-]{1,48})", re.IGNORECASE),
    re.compile(r"\b(?:em|in)\s+([a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ0-9\s,\-]{1,48})\s*(?:\?|$)", re.IGNORECASE),
]


def _read_meminfo_bytes() -> dict:
    total = None
    available = None
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1]) * 1024
                if total is not None and available is not None:
                    break
    except Exception:
        return {"total": None, "available": None}
    return {"total": total, "available": available}


def _read_uptime_human() -> str:
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            seconds = int(float((f.read().split() or ["0"])[0]))
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours:02d}:{minutes:02d}"
        return f"{hours:02d}:{minutes:02d}"
    except Exception:
        return "--"


def _read_cpu_percent() -> float:
    # Lightweight fallback based on load average.
    try:
        load1 = os.getloadavg()[0]
        cpus = max(1, os.cpu_count() or 1)
        return max(0.0, min(100.0, (load1 / cpus) * 100.0))
    except Exception:
        return 0.0


def _normalize_city_candidate(value: str) -> str:
    city = str(value or "").strip(" ,.-")
    if not city:
        return ""
    # Prefer the first segment before region/country qualifiers.
    city = city.split(",")[0].strip(" ,.-")
    # Guard against generic words.
    if city.lower() in {"clima", "tempo", "weather", "forecast", "previsao", "previsão", "regiao", "região"}:
        return ""
    return city


def _infer_weather_city_from_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    for pattern in _WEATHER_CITY_PATTERNS:
        m = pattern.search(raw)
        if not m:
            continue
        candidate = _normalize_city_candidate(m.group(1) or "")
        if candidate:
            return candidate
    return ""


def _infer_weather_city_from_history(session_obj) -> str:
    """
    Infer location/city from recent chat text so weather cards can hydrate even when
    session location context is missing.
    """
    history = getattr(session_obj, "history", None)
    if not isinstance(history, list):
        return ""

    for msg in reversed(history[-20:]):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").lower()
        if role not in {"user", "assistant", "atlas"}:
            continue
        text = str(msg.get("content") or "").strip()
        if not text:
            continue
        city = _infer_weather_city_from_text(text)
        if city:
            return city
    return ""


def _read_top_processes(limit: int = 5) -> list:
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pcpu,pmem,pid,comm", "--sort=-pcpu"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.5,
        )
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        # Skip header
        rows = lines[1:] if len(lines) > 1 else []
        out = []
        for ln in rows[: max(1, limit)]:
            parts = ln.split(None, 3)
            if len(parts) < 4:
                continue
            cpu_s, mem_s, pid_s, name = parts
            try:
                out.append(
                    {
                        "cpu_percent": float(cpu_s.replace(",", ".")),
                        "memory_percent": float(mem_s.replace(",", ".")),
                        "pid": int(pid_s),
                        "name": name,
                    }
                )
            except Exception:
                continue
        return out
    except Exception:
        return []


def _read_network_totals() -> tuple[int, int]:
    rx_total = 0
    tx_total = 0
    try:
        with open("/proc/net/dev", "r", encoding="utf-8") as f:
            for line in f.readlines()[2:]:
                if ":" not in line:
                    continue
                iface, raw = line.split(":", 1)
                iface = iface.strip()
                if iface == "lo":
                    continue
                cols = raw.split()
                if len(cols) < 16:
                    continue
                rx_total += int(cols[0])
                tx_total += int(cols[8])
    except Exception:
        return (0, 0)
    return (rx_total, tx_total)


def _read_network_rates(session_id: str) -> dict:
    now = time.time()
    rx_now, tx_now = _read_network_totals()
    prev = _NET_RATE_SAMPLES.get(session_id)
    _NET_RATE_SAMPLES[session_id] = {"ts": now, "rx": rx_now, "tx": tx_now}

    if not prev:
        return {"rx_kbps": 0.0, "tx_kbps": 0.0, "total_kbps": 0.0, "percent": 0.0}

    dt = max(0.001, now - float(prev.get("ts") or now))
    rx_delta = max(0, rx_now - int(prev.get("rx") or rx_now))
    tx_delta = max(0, tx_now - int(prev.get("tx") or tx_now))

    # kB/s (not kbps bits)
    rx_kbps = rx_delta / dt / 1024.0
    tx_kbps = tx_delta / dt / 1024.0
    total = rx_kbps + tx_kbps

    # Heuristic utilization: 100% at >= 2 MB/s aggregate.
    percent = max(0.0, min(100.0, (total / 2048.0) * 100.0))
    return {
        "rx_kbps": round(rx_kbps, 1),
        "tx_kbps": round(tx_kbps, 1),
        "total_kbps": round(total, 1),
        "percent": round(percent, 1),
    }

def get_kernel(request: Request):
    if not hasattr(request.app.state, "kernel") or not request.app.state.kernel:
        raise HTTPException(status_code=503, detail="Kernel not initialized")
    return request.app.state.kernel


def _clip_text(value, limit: int = 160) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _sample_lines(items, *, max_items: int = 3, max_chars: int = 160) -> list:
    output = []
    for item in list(items or [])[: max_items]:
        text = _clip_text(item, max_chars)
        if text:
            output.append(text)
    return output


def _normalize_counts_map(value) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): int(count)
        for key, count in value.items()
        if str(key).strip() and isinstance(count, (int, float))
    }


def _build_cognitive_state_summary(session_obj) -> dict:
    state = getattr(session_obj, "cognitive_state", None)
    state = state if isinstance(state, dict) else {}
    mission = state.get("mission") if isinstance(state.get("mission"), dict) else {}
    focus = state.get("focus") if isinstance(state.get("focus"), dict) else {}
    open_loops = list(state.get("open_loops") or [])
    blockers = list(state.get("blockers") or [])
    constraints = list(state.get("constraints") or [])
    watchpoints = list(state.get("watchpoints") or [])
    decisions = list(state.get("decisions") or [])
    checkpoints = list(state.get("checkpoints") or [])
    recent_progress = list(state.get("recent_progress") or [])

    return {
        "mission": _clip_text(mission.get("objective"), 220),
        "mission_status": str(mission.get("status") or "").strip(),
        "focus": {
            "primary_task_id": str(focus.get("primary_task_id") or "").strip(),
            "primary_summary": _clip_text(focus.get("primary_summary"), 220),
            "reasoning_mode": str(focus.get("reasoning_mode") or "").strip(),
            "attention_mode": str(focus.get("attention_mode") or "").strip(),
        },
        "open_loops_count": len(open_loops),
        "blockers_count": len(blockers),
        "constraints_count": len(constraints),
        "watchpoints_count": len(watchpoints),
        "decisions_count": len(decisions),
        "checkpoints_count": len(checkpoints),
        "recent_progress_count": len(recent_progress),
        "open_loops_preview": _sample_lines(open_loops),
        "blockers_preview": _sample_lines(blockers),
        "constraints_preview": _sample_lines(constraints),
        "watchpoints_preview": _sample_lines(watchpoints),
        "decisions_preview": _sample_lines(decisions),
        "checkpoints_preview": _sample_lines(checkpoints),
        "recent_progress_preview": _sample_lines(recent_progress),
    }


def _build_projection_summary(session_obj) -> dict:
    projection = getattr(session_obj, "last_cognitive_projection", None)
    projection = projection if isinstance(projection, dict) else {}
    focus_lines = [str(item).strip() for item in list(projection.get("focus_lines") or []) if str(item).strip()]
    background_lines = [str(item).strip() for item in list(projection.get("background_lines") or []) if str(item).strip()]
    return {
        "focus_line_count": len(focus_lines),
        "background_line_count": len(background_lines),
        "focus_lines": focus_lines[:4],
        "background_lines": background_lines[:4],
    }


def _build_latest_cognitive_diagnostics(session_obj) -> dict:
    diagnostics = {}
    context = getattr(session_obj, "context", None)
    if isinstance(context, dict) and isinstance(context.get("last_cognitive_layer"), dict):
        diagnostics = dict(context.get("last_cognitive_layer") or {})
    elif isinstance(getattr(session_obj, "cognitive_diagnostics", None), dict):
        diagnostics = dict(getattr(session_obj, "cognitive_diagnostics") or {})

    return {
        "phase": str(diagnostics.get("phase") or "").strip(),
        "changed_fields": [str(item).strip() for item in list(diagnostics.get("changed_fields") or []) if str(item).strip()][:8],
        "cognitive_fields_populated": [str(item).strip() for item in list(diagnostics.get("cognitive_fields_populated") or []) if str(item).strip()][:10],
        "cognitive_fields_changed": [str(item).strip() for item in list(diagnostics.get("cognitive_fields_changed") or []) if str(item).strip()][:10],
        "cognitive_fields_projected": [str(item).strip() for item in list(diagnostics.get("cognitive_fields_projected") or []) if str(item).strip()][:10],
        "projection_field_sizes": {
            str(key): int(value)
            for key, value in list((diagnostics.get("projection_field_sizes") or {}).items())[:10]
            if str(key).strip() and isinstance(value, (int, float))
        },
        "commit_performed": bool(diagnostics.get("commit_performed")),
        "normalized_outcome_type": str(diagnostics.get("normalized_outcome_type") or "").strip(),
        "outcome_type_generic_fallback_used": bool(diagnostics.get("outcome_type_generic_fallback_used")),
        "fallback_used": bool(diagnostics.get("fallback_used")),
        "fallback_mode": str(diagnostics.get("fallback_mode") or "").strip(),
        "commit_signal_strength": str(diagnostics.get("commit_signal_strength") or "").strip(),
        "planner_relevance_signal": bool(diagnostics.get("planner_relevance_signal")),
        "hint_generated": bool(diagnostics.get("broker_hints_generated")),
        "hint_applied": bool(diagnostics.get("hint_applied")),
        "hint_ignored": bool(diagnostics.get("hint_ignored")),
        "hint_suppressed": bool(diagnostics.get("hint_suppressed")),
        "hinted_domains": [str(item).strip() for item in list(diagnostics.get("hinted_domains") or []) if str(item).strip()][:8],
        "hint_impact_summary": [str(item).strip() for item in list(diagnostics.get("hint_impact_summary") or []) if str(item).strip()][:8],
        "ranking_changed_by_hint": bool(diagnostics.get("ranking_changed_by_hint")),
        "strategic_updates_summary": [str(item).strip() for item in list(diagnostics.get("strategic_updates_summary") or []) if str(item).strip()][:8],
        "commit_noise_suppressed_count": int(diagnostics.get("commit_noise_suppressed_count") or 0),
        "outcome_refined": bool(diagnostics.get("outcome_refined")),
        "strategic_field_pruned_count": int(diagnostics.get("strategic_field_pruned_count") or 0),
        "effectiveness_flags": [str(item).strip() for item in list(diagnostics.get("effectiveness_flags") or []) if str(item).strip()][:8],
    }


def _build_broker_cross_telemetry(session_obj) -> dict:
    context = getattr(session_obj, "context", None)
    broker = context.get("last_context_broker") if isinstance(context, dict) and isinstance(context.get("last_context_broker"), dict) else {}
    queried = broker.get("queried_domains") if isinstance(broker.get("queried_domains"), dict) else {}
    queried_domains = [str(key) for key, active in queried.items() if active]
    return {
        "evidence_present": bool(broker.get("evidence_count")),
        "evidence_count": int(broker.get("evidence_count") or 0),
        "domains_queried": queried_domains[:8],
        "evidence_domains": [str(item).strip() for item in list(broker.get("evidence_domains") or []) if str(item).strip()][:8],
        "evidence_counts_by_domain_selected": {
            str(key): int(value)
            for key, value in list((broker.get("evidence_counts_by_domain_selected") or {}).items())[:10]
            if str(key).strip() and isinstance(value, (int, float))
        },
        "evidence_counts_by_domain_suppressed": {
            str(key): int(value)
            for key, value in list((broker.get("evidence_counts_by_domain_suppressed") or {}).items())[:10]
            if str(key).strip() and isinstance(value, (int, float))
        },
        "rerank_win_by_domain": {
            str(key): int(value)
            for key, value in list((broker.get("rerank_win_by_domain") or {}).items())[:10]
            if str(key).strip() and isinstance(value, (int, float))
        },
        "domain_conflict_resolution_summary": [
            str(item).strip() for item in list(broker.get("domain_conflict_resolution_summary") or []) if str(item).strip()
        ][:8],
        "total_evidence_chars": int(broker.get("total_evidence_chars") or 0),
        "evidence_density_reduction_count": int(broker.get("evidence_density_reduction_count") or 0),
        "low_value_suppressed_count": int(broker.get("low_value_suppressed_count") or 0),
        "hint_present": bool(broker.get("hint_present")),
        "hint_applied": bool(broker.get("hint_applied")),
        "hint_ignored": bool(broker.get("hint_ignored")),
        "hinted_domains": [str(item).strip() for item in list(broker.get("hinted_domains") or []) if str(item).strip()][:8],
        "hint_impact_summary": [str(item).strip() for item in list(broker.get("hint_impact_summary") or []) if str(item).strip()][:8],
        "hint_ranking_changed": bool(broker.get("hint_ranking_changed")),
    }


def _build_cognition_snapshot_payload(session_obj) -> dict:
    counters = {}
    context = getattr(session_obj, "context", None)
    if isinstance(context, dict) and isinstance(context.get("cognitive_effectiveness_counters"), dict):
        counters = dict(context.get("cognitive_effectiveness_counters") or {})

    diagnostics = _build_latest_cognitive_diagnostics(session_obj)
    return {
        "session_id": getattr(session_obj, "session_id", ""),
        "source": getattr(session_obj, "source", "web"),
        "turn_id": int(getattr(session_obj, "turn_id", 0) or 0),
        "current_cognitive_state": _build_cognitive_state_summary(session_obj),
        "last_cognitive_projection": _build_projection_summary(session_obj),
        "last_cognitive_layer": diagnostics,
        "hint_telemetry": {
            "generated": bool(diagnostics.get("hint_generated")),
            "applied": bool(diagnostics.get("hint_applied")),
            "ignored": bool(diagnostics.get("hint_ignored")),
            "suppressed": bool(diagnostics.get("hint_suppressed")),
            "hinted_domains": list(diagnostics.get("hinted_domains") or [])[:8],
            "hint_impact_summary": list(diagnostics.get("hint_impact_summary") or [])[:8],
            "ranking_changed_by_hint": bool(diagnostics.get("ranking_changed_by_hint")),
        },
        "outcome_coverage": {
            "counts_by_type": _normalize_counts_map(counters.get("outcome_types")),
            "generic_fallback_count": int(counters.get("generic_outcomes") or 0),
            "generic_fallback_streak": int(counters.get("generic_outcome_streak") or 0),
        },
        "strategic_usefulness": {
            "fields_populated": list(diagnostics.get("cognitive_fields_populated") or [])[:10],
            "fields_changed": list(diagnostics.get("cognitive_fields_changed") or [])[:10],
            "fields_projected": list(diagnostics.get("cognitive_fields_projected") or [])[:10],
            "projection_field_sizes": dict(diagnostics.get("projection_field_sizes") or {}),
            "commit_signal_strength": str(diagnostics.get("commit_signal_strength") or "").strip(),
            "planner_relevance_signal": bool(diagnostics.get("planner_relevance_signal")),
            "commit_noise_suppressed_count": int(diagnostics.get("commit_noise_suppressed_count") or 0),
            "strategic_field_pruned_count": int(diagnostics.get("strategic_field_pruned_count") or 0),
        },
        "fallback_telemetry": {
            "fallback_used": bool(diagnostics.get("fallback_used")),
            "fallback_mode": str(diagnostics.get("fallback_mode") or "").strip(),
            "reconcile_turns": int(counters.get("reconcile_turns") or 0),
            "commit_turns": int(counters.get("commit_turns") or 0),
        },
        "broker_cross_telemetry": _build_broker_cross_telemetry(session_obj),
    }


def _build_cognition_counters_payload(session_obj) -> dict:
    context = getattr(session_obj, "context", None)
    counters = context.get("cognitive_effectiveness_counters") if isinstance(context, dict) and isinstance(context.get("cognitive_effectiveness_counters"), dict) else {}
    return {
        "session_id": getattr(session_obj, "session_id", ""),
        "reconcile_turns": int(counters.get("reconcile_turns") or 0),
        "commit_turns": int(counters.get("commit_turns") or 0),
        "hints_generated": int(counters.get("hints_generated") or 0),
        "hints_applied": int(counters.get("hints_applied") or 0),
        "hints_ignored": int(counters.get("hints_ignored") or 0),
        "hint_suppressed_count": int(counters.get("hint_suppressed_count") or 0),
        "hint_routing_impacts": int(counters.get("hint_routing_impacts") or 0),
        "hint_ranking_impacts": int(counters.get("hint_ranking_impacts") or 0),
        "projection_non_empty_turns": int(counters.get("projection_non_empty_turns") or 0),
        "planner_relevance_turns": int(counters.get("planner_relevance_turns") or 0),
        "strategic_update_turns": int(counters.get("strategic_update_turns") or 0),
        "generic_outcomes": int(counters.get("generic_outcomes") or 0),
        "generic_outcome_streak": int(counters.get("generic_outcome_streak") or 0),
        "outcome_types": _normalize_counts_map(counters.get("outcome_types")),
        "commit_signal_strength": _normalize_counts_map(counters.get("commit_signal_strength")),
        "commit_noise_suppressed_count": int(counters.get("commit_noise_suppressed_count") or 0),
        "outcome_refined_count": int(counters.get("outcome_refined_count") or 0),
        "strategic_field_pruned_count": int(counters.get("strategic_field_pruned_count") or 0),
    }


def _user_visible_history(history: list) -> list:
    visible = []
    for msg in history or []:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("type") or "").strip().lower() == "reasoning":
            continue
        visible.append(msg)
    return visible

@router.get("")
@router.get("/")
def list_sessions(request: Request, interface: str = "all", user: User = Depends(get_current_user)):
    """
    List all sessions for an interface, ordered by last_opened_at.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    return orch.get_sessions_list(interface)

@router.get("/active")
def get_active_session(request: Request, interface: str = "web", user: User = Depends(get_current_user)):
    """
    Get the session that should be opened automatically.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_active_session(interface)
    if not session:
        return {"id": None, "source": interface, "is_new": True}
        
    return {
        "id": session.session_id,
        "source": session.source,
        "is_new": False
    }

@router.post("")
@router.post("/")
def create_session(request: Request, payload: dict = None, user: User = Depends(get_current_user)):
    """
    Create a new session.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    interface = payload.get("interface", "web") if payload else "web"
    name = payload.get("name", "") if payload else ""
    import uuid
    # Enforce naming convention: if web, prefix with web-
    session_id = f"{interface}-{str(uuid.uuid4())[:8]}"
    
    session = orch.create_session(session_id, interface, name=name)
    
    return {"id": session_id, "source": interface, "name": name}

@router.post("/{session_id}/open")
def open_session(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Mark a session as recently opened.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.open_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    return {"status": "success", "session_id": session_id, "last_opened_at": session.last_opened_at}

@router.get("/{session_id}")
def get_session(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Get session state and only the most recent history for initial load.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        # If it's a new lazy session search, avoid 500
        return {"id": session_id, "source": "web", "name": "", "history": [], "is_new": True}

    # Timeline source of truth must be chat.json (not session.json context snapshot).
    history = _user_visible_history(orch.get_chat_history(session_id))

    return {
        "id": session.session_id,
        "session_id": session.session_id,
        "source": getattr(session, 'source', 'web'),
        "interface": getattr(session, 'source', 'web'),
        "name": getattr(session, 'name', ''),
        "profile_picture": getattr(session, 'profile_picture', None),
        "history": history[-15:] if len(history) > 15 else history,
        "context": session.context,
        "scratchpad": session.scratchpad,
        "runtime_metrics": orch.get_runtime_metrics(session_id) if hasattr(orch, "get_runtime_metrics") else {},
    }


@router.get("/{session_id}/snapshot")
def get_session_snapshot(
    session_id: str,
    request: Request,
    recent_events_limit: int = 100,
    user: User = Depends(get_current_user),
):
    """
    Return a canonical backend snapshot for initial load or reload flows.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator

    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    from core.session_event_pipeline import build_session_snapshot

    snapshot = build_session_snapshot(
        session_id,
        base_data_dir=getattr(kernel.config_manager, "base_data_dir", None),
        recent_events_limit=recent_events_limit,
    )
    snapshot["session"] = snapshot.get("session") or session.to_dict()
    snapshot["current"] = {
        "session_id": session.session_id,
        "source": getattr(session, "source", "web"),
        "name": getattr(session, "name", ""),
        "profile_picture": getattr(session, "profile_picture", None),
        "turn_id": getattr(session, "turn_id", 0),
        "context": session.context,
        "scratchpad": session.scratchpad,
    }
    snapshot["runtime_metrics"] = orch.get_runtime_metrics(session_id) if hasattr(orch, "get_runtime_metrics") else {}
    return snapshot


@router.get("/{session_id}/cognition")
def get_session_cognition(session_id: str, request: Request, user: User = Depends(get_current_user)):
    kernel = get_kernel(request)
    orch = kernel.orchestrator

    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    payload = _build_cognition_snapshot_payload(session)
    payload["counters"] = _build_cognition_counters_payload(session)
    return payload


@router.get("/{session_id}/cognition/snapshot")
def get_session_cognition_snapshot(session_id: str, request: Request, user: User = Depends(get_current_user)):
    kernel = get_kernel(request)
    orch = kernel.orchestrator

    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return _build_cognition_snapshot_payload(session)


@router.get("/{session_id}/cognition/counters")
def get_session_cognition_counters(session_id: str, request: Request, user: User = Depends(get_current_user)):
    kernel = get_kernel(request)
    orch = kernel.orchestrator

    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return _build_cognition_counters_payload(session)

@router.patch("/{session_id}")
def update_session(session_id: str, payload: dict, request: Request, user: User = Depends(get_current_user)):
    """
    Update session properties like name.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    if "name" in payload:
        session.name = payload["name"]
        
        # Persist the change
        orch._save_session(session)
        
        # Notify web sockets via the canonical session event pipeline.
        from core.session_event_pipeline import record_session_event
        record_session_event(
            session,
            {
                "type": "session_updated",
                "session_id": session.session_id,
                "name": session.name,
                "payload": {"name": session.name},
                "source": "sessions_route",
            },
            defaults={"source": "sessions_route"},
            publish=True,
        )
        
    return {"status": "success", "session_id": session.session_id, "name": session.name}

@router.put("/{session_id}/read")
def mark_session_read(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """Marks all assistant messages in a session as read."""
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    if session.mark_as_read("assistant"):
        orch._save_session(session)
        # Notify via event bus that unread count changed
        from utils.event_bus import global_event_bus
        global_event_bus.emit_threadsafe({
            "type": "unread_count_updated",
            "session_id": session_id,
            "unread_count": 0
        })
        
    return {"status": "success", "session_id": session_id}

@router.get("/{session_id}/history")
def get_session_history(session_id: str, offset: int = 0, limit: int = 15, request: Request = None, user: User = Depends(get_current_user)):
    """
    Get paginated history for a session.
    offset: number of messages to skip from the END (e.g., offset=0 means last 'limit' messages)
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Timeline source of truth must be chat.json (not session.json context snapshot).
    history = _user_visible_history(orch.get_chat_history(session_id))
    total = len(history)
    
    # Calculate indices from the end
    end_idx = total - offset
    start_idx = max(0, end_idx - limit)

    if end_idx <= 0 or start_idx >= total:
        paginated = []
    else:
        paginated = history[start_idx:end_idx]
        
    return {
        "id": session_id,
        "history": paginated,
        "total": total,
        "has_more": start_idx > 0
    }

@router.get("/{session_id}/thoughts")
def get_session_thoughts(session_id: str, message_id: str = None, request: Request = None, user: User = Depends(get_current_user)):
    """
    Get the cognitive audit trail (thoughts) for a session.
    Optional message_id query parameter filters thoughts correlated to a specific assistant response.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        return { "id": session_id, "thoughts": [], "total": 0 }

    thoughts = getattr(session, "thoughts", [])
    
    if message_id:
        thoughts = [t for t in thoughts if str(t.get("message_id")) == str(message_id)]
        
    return {
        "id": session_id,
        "thoughts": thoughts,
        "total": len(thoughts)
    }

@router.get("/{session_id}/cards")
def get_session_cards(session_id: str, request: Request = None, user: User = Depends(get_current_user)):
    """
    Get the historic UI media cards for a session.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        return { "id": session_id, "cards": [], "total": 0 }

    cards = getattr(session, "media_cards", [])
    
    return {
        "id": session_id,
        "cards": cards,
        "total": len(cards)
    }

@router.post("/{session_id}/cards")
async def add_session_card(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Add a new media card snapshot to the session's persistence layer.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        card_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
    if not isinstance(card_data, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    card_id = session.add_media_card(card_data)
    
    # Save the session to write the cards.json update
    orch._save_session(session)
    
    return {"status": "success", "card_id": card_id}

@router.post("/{session_id}/wegena/feedback")
async def add_wegena_feedback(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Registrar feedback (like/dislike) para a cena gerada pelo wegena.
    No futuro isso será persistido e alimentará a base de treinamento do RAG.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        data = await request.json()
        feedback_type = data.get("feedback_type")
        script_url = data.get("script_url", "")
        if feedback_type not in ("like", "dislike"):
            raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload, must contain feedback_type 'like' or 'dislike'")
        
    config_manager = kernel.config_manager
    wegena_config = config_manager.get("capabilities", {}).get("wegena", {})
    learning_enabled = wegena_config.get("feedback_learning_enabled", True)

    if learning_enabled:
        os.makedirs("data/workspace/wegena", exist_ok=True)
        rag_path = os.path.join("data/workspace/wegena", "feedback_rag.jsonl")
        
        record = {
            "session_id": session_id,
            "timestamp": time.time(),
            "feedback": feedback_type,
            "user_id": user.id if user else "anonymous",
            "script_url": script_url
        }
        
        try:
            with open(rag_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            logger.info(f"Wegena Feedback salvo no RAG DB: {record}")
        except Exception as e:
            logger.error(f"Falha ao salvar feedback RAG: {e}")
    else:
        logger.info(f"Wegena Feedback ignorado (learning disabled): session={session_id}, type={feedback_type}")
    
    return {"status": "success", "feedback_type": feedback_type, "saved_to_rag": learning_enabled}
@router.post("/{session_id}/message")
def send_message(session_id: str, payload: dict, request: Request, user: User = Depends(get_current_user)):
    """
    Send a message as 'user' or 'operator'.
    """
    message = payload.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="Message required")

    attachments = payload.get("attachments", []) or []
    user_data = payload.get("user_data", {}) or {}
    if not isinstance(user_data, dict):
        user_data = {}
    user_data.setdefault("user_name", user.display_name or user.username)
    user_data.setdefault("portal_user_id", user.id)
    user_data.setdefault("portal_username", user.username)
        
    kernel = get_kernel(request)
    
    # We need a way to inject input into the Kernel for a specific session.
    # The Kernel.process_input method takes a 'driver_instance'.
    # We should use the ServerDriver instance.
    
    # Find ServerDriver
    server_driver = next((d for d in kernel.drivers if hasattr(d, 'app')), None)
    if not server_driver:
         # Fallback if we can't find it easily, but we are running INSIDE the server driver context practically
         # Actually, we can just pass 'None' as driver if we handle the response properly?
         # No, Kernel needs a driver to send response back to.
         raise HTTPException(status_code=500, detail="ServerDriver not found to route message")

    # Inject input
    # Note: process_input is async-ish (spawns thread).
    context = PrincipalContext(
        interface="web",
        sender_id=f"user_{user.id}",
        sender_name=user.display_name or user.username,
        session_id=session_id,
    )
    kernel.process_input(
        message,
        server_driver,
        user_id=session_id,
        user_data=user_data,
        context=context,
        attachments=attachments,
    )
    
    return {"status": "sent", "message": message}

@router.post("/{session_id}/inject")
def inject_system_message(session_id: str, payload: dict, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Inject a SYSTEM message or command. Admin only.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
        
    message = payload.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="Message required")

    kernel = get_kernel(request)
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Inject directly into history without triggering LLM immediately?
    # Or trigger LLM with system prompt?
    # Usually 'inject' means "Pretend the system said this" or "Add invisible instruction".
    
    session.add_message("system", message)
    # orch._save_session(session) # If accessible
    
    # Audit
    db.add(AuditLog(
        user_id=user.id,
        username=user.username,
        action="inject_message",
        target=session_id,
        details=json.dumps({"len": len(message)})
    ))
    db.commit()
    
    return {"status": "injected", "role": "system"}

@router.post("/{session_id}/profile_picture")
async def upload_profile_picture(
    session_id: str, 
    request: Request, 
    file: UploadFile = File(...), 
    user: User = Depends(get_current_user)
):
    """
    Upload a profile picture for a session.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    upload_dir = os.path.join(kernel.orchestrator.sessions_dir, session_id, "media", "profile_picture")
    os.makedirs(upload_dir, exist_ok=True)
    
    file_path = os.path.join(upload_dir, f"avatar_{file.filename}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    relative_path = f"media/profile_picture/avatar_{file.filename}"
    session.profile_picture = relative_path
    orch._save_session(session)
    
    from core.session_event_pipeline import record_session_event
    record_session_event(
        session,
        {
            "type": "session_updated",
            "session_id": session.session_id,
            "profile_picture": session.profile_picture,
            "payload": {"profile_picture": session.profile_picture},
            "source": "sessions_route",
        },
        defaults={"source": "sessions_route"},
        publish=True,
    )
    
    return {
        "status": "success",
        "profile_picture": relative_path
    }

@router.post("/{session_id}/upload")
async def upload_files(
    session_id: str, 
    request: Request, 
    files: list[UploadFile] = File(...), 
    user: User = Depends(get_current_user)
):
    """
    Upload multiple files/images to a session (Max 10).
    """
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum of 10 files at a time.")

    kernel = get_kernel(request)
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    
    if not session:
        # Auto-create if not found but message is being sent (Lazy Creation)
        interface = "web" # Default for API
        session = orch.create_session(session_id, interface)
        
    # Target directory: data/sessions/{session_id}/media/{file_type}
    # Standardized with AgentOrchestrator.standardize_attachments logic
    uploaded_info = []
    
    for file in files:
        # Determine type based on content type
        file_type = "file"
        if file.content_type and file.content_type.startswith("image/"): file_type = "image"
        elif file.content_type and file.content_type.startswith("video/"): file_type = "video"
        elif file.content_type and file.content_type.startswith("audio/"): file_type = "audio"
        
        target_dir = os.path.join(kernel.orchestrator.sessions_dir, session_id, "media", file_type)
        os.makedirs(target_dir, exist_ok=True)
        
        file_path = os.path.join(target_dir, file.filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_metadata = {
            "name": file.filename,
            "filename": file.filename,  # Backward-compatible alias
            "path": file_path,
            "type": file_type,
            "mime": file.content_type or "application/octet-stream"
        }
        uploaded_info.append(file_metadata)

    # Metadata is returned to the frontend, which will send a UNIFIED message 
    # via WebSocket/API containing both text and these attachments.
    # This prevents split messages and technical "Local: /path/..." text in the UI.
    
    return {
        "status": "uploaded",
        "count": len(files),
        "files": uploaded_info
    }
@router.delete("/{session_id}")
def delete_session(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Delete a session and all its associated data.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    orch.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}

@router.get("/{session_id}/media")
def get_session_media(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Returns media files and extracted links for a specific session.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    return orch.get_session_media(session_id)
@router.get("/{session_id}/traces")
def get_session_decision_traces(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """Returns structured decision traces for a session."""
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return getattr(session, "decision_traces", [])

@router.get("/{session_id}/timeline")
def get_session_timeline(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """Returns the holistic event timeline for a session."""
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return getattr(session, "event_timeline", [])

@router.get("/{session_id}/events")
async def stream_session_events(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Streams events for a specific session via SSE.
    """
    from utils.event_bus import global_event_bus
    import asyncio
    
    async def event_generator():
        queue = global_event_bus.subscribe()
        try:
            # Initial connection event
            yield f"data: {json.dumps({'type': 'connection', 'status': 'connected', 'session_id': session_id})}\n\n"
            
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    # Filter events by session_id if provided in event
                    # If event has session_id, it must match. If it doesn't, we send it anyway (global event)
                    if event.get("session_id") and event["session_id"] != session_id:
                        continue
                        
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            global_event_bus.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/{session_id}/playback")
def list_playback_runs(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """Lists all playback runs for a session, with manifest summaries."""
    kernel = get_kernel(request)
    playback_dir = os.path.join(kernel.orchestrator.sessions_dir, session_id, "playback")
    
    if not os.path.isdir(playback_dir):
        return {"runs": []}
    
    runs = []
    for run_id in sorted(os.listdir(playback_dir), reverse=True):
        manifest_path = os.path.join(playback_dir, run_id, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            # Get first frame as thumbnail
            frames_dir = os.path.join(playback_dir, run_id, "frames")
            first_frame = None
            if os.path.isdir(frames_dir):
                frame_files = sorted(os.listdir(frames_dir))
                if frame_files:
                    first_frame = f"/api/sessions/{session_id}/playback/{run_id}/frames/{frame_files[0]}"
            
            runs.append({
                "run_id": run_id,
                "title": manifest.get("title", "Browser Session"),
                "status": manifest.get("status", "unknown"),
                "total_steps": len(manifest.get("steps", [])),
                "thumbnail": first_frame,
                "created_at": os.path.getmtime(manifest_path),
            })
        except Exception:
            continue
    
    return {"runs": runs}


@router.get("/{session_id}/cards/weather")
def get_weather_card(
    session_id: str,
    request: Request,
    days: int = 3,
    hint: str | None = None,
    user: User = Depends(get_current_user),
):
    """
    Returns structured weather data for assistive chat cards.
    Uses weather capability + current session context (location fallback included).
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    capabilities_cfg = kernel.config_manager.get("capabilities", {}) if hasattr(kernel, "config_manager") else {}
    weather_cfg = capabilities_cfg.get("weather_control", {}) if isinstance(capabilities_cfg, dict) else {}
    weather_capability = WeatherCapability(kernel=kernel, config=weather_cfg)
    safe_days = max(1, min(int(days or 3), 5))
    ctx = {"session": session}
    inferred_city = _infer_weather_city_from_text(hint or "") or _infer_weather_city_from_history(session)
    weather_params = {"city": inferred_city} if inferred_city else {}

    current_payload = weather_capability.execute("weather.control.get", weather_params, ctx)
    if not isinstance(current_payload, dict) or not current_payload.get("ok"):
        return {
            "ok": False,
            "card_type": "weather",
            "error": (current_payload or {}).get("error", "WEATHER_UNAVAILABLE"),
            "message": (current_payload or {}).get("message", "Weather data unavailable."),
        }

    forecast_params = {"days": safe_days, **weather_params}
    forecast_payload = weather_capability.execute("weather.control.forecast", forecast_params, ctx)
    if not isinstance(forecast_payload, dict) or not forecast_payload.get("ok"):
        forecast_payload = {"ok": False, "forecast": [], "days": 0}

    provider = current_payload.get("provider") or forecast_payload.get("provider") or "unknown"
    location_name = current_payload.get("location") or forecast_payload.get("location") or "Unknown"

    if isinstance(getattr(session, "context", None), dict):
        session.context["weather"] = {
            "ok": True,
            "provider": provider,
            "location": location_name,
            "current": current_payload.get("current", {}),
            "updated_at": time.time(),
        }
        if hasattr(orch, "_save_session"):
            orch._save_session(session)

    return {
        "ok": True,
        "card_type": "weather",
        "provider": provider,
        "location": location_name,
        "current": current_payload.get("current", {}),
        "forecast": forecast_payload.get("forecast", []),
        "days": int(forecast_payload.get("days") or 0),
    }


@router.get("/{session_id}/cards/system-health")
def get_system_health_card(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    """
    Returns structured host/system health data for assistive chat cards.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    mem = _read_meminfo_bytes()
    total_mem = mem.get("total")
    avail_mem = mem.get("available")
    mem_percent = None
    if isinstance(total_mem, int) and total_mem > 0 and isinstance(avail_mem, int):
        mem_percent = max(0.0, min(100.0, ((total_mem - avail_mem) / total_mem) * 100.0))

    try:
        du = shutil.disk_usage("/")
        disk_total = int(du.total)
        disk_free = int(du.free)
        disk_percent = max(0.0, min(100.0, ((disk_total - disk_free) / max(1, disk_total)) * 100.0))
    except Exception:
        disk_total = None
        disk_free = None
        disk_percent = None

    try:
        load_avg = [float(v) for v in os.getloadavg()]
    except Exception:
        load_avg = []
    net = _read_network_rates(session_id)

    payload = {
        "ok": True,
        "card_type": "system_health",
        "provider": "local_system",
        "cpu_usage_percent": round(_read_cpu_percent(), 1),
        "memory_percent": round(mem_percent or 0.0, 1),
        "disk_percent": round(disk_percent or 0.0, 1),
        "network_percent": round(float(net.get("percent") or 0.0), 1),
        "load_avg": load_avg,
        "temperature_c": None,
        "uptime": _read_uptime_human(),
        "memory_total": total_mem,
        "memory_available": avail_mem,
        "disk_total": disk_total,
        "disk_free": disk_free,
        "network_rx_kbps": float(net.get("rx_kbps") or 0.0),
        "network_tx_kbps": float(net.get("tx_kbps") or 0.0),
        "network_total_kbps": float(net.get("total_kbps") or 0.0),
        "top_processes": _read_top_processes(limit=6),
        "ts": int(time.time()),
    }
    return payload

@router.get("/{session_id}/playback/{run_id}/manifest")
def get_playback_manifest(session_id: str, run_id: str, request: Request, user: User = Depends(get_current_user)):
    """Returns the manifest for a specific playback run."""
    kernel = get_kernel(request)
    path = os.path.join(kernel.orchestrator.sessions_dir, session_id, "playback", run_id, "manifest.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Playback manifest not found")
    
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

@router.get("/{session_id}/playback/{run_id}/frames/{filename:path}")
def get_playback_frame(session_id: str, run_id: str, filename: str, request: Request, user: User = Depends(get_current_user)):
    """Returns a specific frame image for a playback run."""
    kernel = get_kernel(request)
    # Basic security: normalize path to prevent traversal
    filename = os.path.basename(filename)
    path = os.path.join(kernel.orchestrator.sessions_dir, session_id, "playback", run_id, "frames", filename)
    
    if not os.path.exists(path):
        # Playback viewers poll future frames; avoid noisy 404 spam for normal tailing.
        return Response(status_code=204)
        
    return FileResponse(path, media_type="image/jpeg")

@router.get("/{session_id}/files/{filename:path}")
def get_session_file(session_id: str, filename: str, request: Request, user: User = Depends(get_current_user)):
    """
    Securely serves a file from the session's workspace or uploads folder.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    # Security: Prevent directory traversal
    filename = os.path.normpath(filename)
    if filename.startswith("..") or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Check search locations: 
    # 1. uploads/ (session specific)
    # 2. workspace/ (shared)
    
    locations = [
        os.path.join(orch.sessions_dir, session_id, "uploads", filename),
        os.path.join(orch.sessions_dir, session_id, filename), # Supports media/type/filename
        os.path.join(kernel.workspace_service.get_workspace_dir(), filename),
        os.path.join(
            kernel.workspace_service.get_workspace_dir(),
            "temp",
            session_id,
            filename[len("media/image/temp/") :] if filename.startswith("media/image/temp/") else filename,
        ),
        os.path.join(kernel.workspace_service.output_dir, "exports", filename)
    ]
    
    for path in locations:
        if os.path.exists(path) and os.path.isfile(path):
             # Ensure the path is still within a safe root
             if any(path.startswith(os.path.abspath(r)) for r in [orch.sessions_dir, kernel.workspace_service.base_dir]):
                return FileResponse(path)
                
    raise HTTPException(status_code=404, detail=f"File {filename} not found in session {session_id}")
