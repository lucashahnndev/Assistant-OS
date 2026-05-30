from __future__ import annotations

from typing import Any, Dict, List
import json


def _short_text(value: Any, limit: int = 96) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _risk_code(value: Any) -> str:
    v = str(value or "").strip().lower()
    if v == "low":
        return "l"
    if v == "medium":
        return "m"
    if v == "high":
        return "h"
    return "u"


def _clean_obj(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in data.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = v
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, (list, dict)) and len(v) == 0:
            continue
        if isinstance(v, (int, float)) and v == 0:
            continue
        out[k] = v
    return out


def encode_capabilities_list(rows: List[Dict[str, Any]], include_description: bool = True) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for row in rows:
        item: Dict[str, Any] = {
            "a": str(row.get("id") or ""),
            "ns": str(row.get("namespace") or ""),
            "r": _risk_code(row.get("risk_level")),
        }
        if include_description:
            item["d"] = _short_text(row.get("description"), limit=80)
        items.append(item)

    return {
        "v": "toon.v1",
        "t": "capabilities.list",
        "n": len(items),
        "i": items,
    }


def encode_capabilities_describe(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for row in rows:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        params = meta.get("parameters") if isinstance(meta.get("parameters"), dict) else {}
        props = params.get("properties") if isinstance(params.get("properties"), dict) else {}
        required = params.get("required") if isinstance(params.get("required"), list) else []

        item: Dict[str, Any] = {
            "a": str(row.get("id") or ""),
            "ok": bool(row.get("ok")),
        }

        if not item["ok"]:
            item["e"] = str(row.get("error") or "UNKNOWN")
            items.append(item)
            continue

        item["r"] = _risk_code(meta.get("risk_level"))
        item["d"] = _short_text(meta.get("description"), limit=96)
        item["req"] = [str(x) for x in required[:16]]
        item["opt"] = [str(k) for k in list(props.keys())[:24] if k not in item["req"]]
        items.append(item)

    return {
        "v": "toon.v1",
        "t": "capabilities.describe",
        "n": len(items),
        "i": items,
    }


def encode_state_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    src = summary if isinstance(summary, dict) else {}
    payload = {
        "v": "toon.v1",
        "t": "state",
        "g": _short_text(src.get("goal"), 80),
        "c": _short_text(src.get("cursor"), 80),
        "d": [str(x) for x in (src.get("done_steps") or [])[:8]],
        "o": _short_text(src.get("last_outcome"), 120),
        "e": _short_text(src.get("last_error"), 80),
        "lo": _short_text(src.get("last_observation") or src.get("last_observation_summary"), 120),
        "le": _short_text(src.get("last_observation_evidence") or src.get("last_observation_evidence_summary"), 220),
        "lc": int(src.get("last_observation_evidence_count", 0) or 0),
        "lsn": int(src.get("last_observation_evidence_shown", 0) or 0),
        "lt": bool(src.get("last_observation_evidence_truncated")),
        "ls": _short_text(src.get("last_observation_status"), 24),
        "lr": _short_text(src.get("last_observation_reason"), 80),
        "rp": bool(src.get("last_observation_requires_replan")),
        "lot": int(src.get("last_observation_turn_id", 0) or 0),
        "low": _short_text(src.get("last_observation_work_id"), 48),
        "loa": _short_text(src.get("last_observation_source_action"), 48),
        "lxa": _short_text(json.dumps(src.get("last_observation_source_args") or {}, ensure_ascii=False, separators=(",", ":")), 120),
        "lof": _short_text(src.get("last_observation_freshness"), 24),
        "lad": _short_text(src.get("last_attachment_delivery_status"), 24),
        "laq": int(src.get("last_attachment_delivery_requested_count", 0) or 0),
        "lar": int(src.get("last_attachment_delivery_resolved_count", 0) or 0),
        "lap": int(src.get("last_attachment_delivery_prepared_count", 0) or 0),
        "las": int(src.get("last_attachment_delivery_sent_count", 0) or 0),
        "lae": int(src.get("last_attachment_delivery_error_count", 0) or 0),
        "lac": bool(src.get("last_attachment_delivery_confirmed")),
        "r": int(src.get("retry_count", 0) or 0),
    }
    return _clean_obj(payload)


def encode_reasoning_step(
    *,
    thought: Any,
    plan: Any,
    action: Any,
    params: Any,
) -> Dict[str, Any]:
    compact_plan: List[str] = []
    if isinstance(plan, list):
        for item in plan[:4]:
            raw = str(item or "").strip()
            # Compresses common planner prefixes: "[x] ", "[/] ", "[ ] "
            if len(raw) >= 4 and raw[0] == "[" and raw[2] == "]":
                raw = raw[4:].strip()
            text = _short_text(raw, 42)
            if text:
                compact_plan.append(text)

    compact_params: Dict[str, Any] = {}
    if isinstance(params, dict):
        for idx, (k, v) in enumerate(params.items()):
            if idx >= 6:
                break
            if isinstance(v, (int, float, bool)) or v is None:
                compact_params[str(k)] = v
            else:
                compact_params[str(k)] = _short_text(v, 56)

    payload = {
        "v": "toon.v1",
        "t": "step",
        "th": _short_text(thought, 120),
        "p": compact_plan,
        "a": str(action or ""),
        "x": compact_params,
    }
    return _clean_obj(payload)


def dumps_toon(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
