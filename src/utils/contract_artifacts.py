import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional


_LOCK = threading.Lock()


def _root_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _contracts_dir() -> str:
    path = os.path.join(_root_dir(), "data", "logs", "contracts")
    os.makedirs(path, exist_ok=True)
    return path


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _preview(value: Any, limit: int = 1200) -> str:
    raw = str(value or "")
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "...<truncated>"


def _safe_json_load(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _safe_json_dump(path: str, payload: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def classify_contract_error(error_text: str) -> str:
    text = str(error_text or "").lower()
    if "empty" in text:
        return "empty_output"
    if "fence is malformed" in text:
        return "malformed_fence"
    if "not valid json" in text:
        return "invalid_json"
    if "must be a json object" in text:
        return "non_object_json"
    if "invalid step_status" in text:
        return "invalid_step_status"
    if "missing required action" in text:
        return "missing_action"
    if "requires" in text and "action" in text:
        return "action_args_violation"
    if "canonical browser planner payload has unexpected shape" in text:
        return "unexpected_shape"
    if "vision" in text and "invalid" in text:
        return "vision_contract_invalid"
    return "contract_violation"


def write_contract_violation(
    *,
    provider: str,
    model: str,
    contract_name: str,
    prompt: str,
    raw_response: Any,
    error_text: str,
    attempt: int = 1,
    max_attempts: int = 1,
    session_id: str = "",
    work_id: str = "",
    trace_id: str = "",
    step_id: str = "",
    parsed_action: str = "",
    expected_action: str = "",
    error_path: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    ts = _utc_now_iso()
    error_code = classify_contract_error(error_text)
    record = {
        "timestamp": ts,
        "provider": str(provider or ""),
        "model": str(model or ""),
        "contract_name": str(contract_name or ""),
        "attempt": int(attempt),
        "max_attempts": int(max_attempts),
        "session_id": str(session_id or ""),
        "work_id": str(work_id or ""),
        "trace_id": str(trace_id or ""),
        "step_id": str(step_id or ""),
        "error_code": error_code,
        "error_text": str(error_text or ""),
        "error_path": str(error_path or ""),
        "action_expected": str(expected_action or ""),
        "action_parsed": str(parsed_action or ""),
        "prompt_fingerprint": _sha256_hex(str(prompt or "")),
        "response_fingerprint": _sha256_hex(str(raw_response or "")),
        "raw_response_excerpt": _preview(raw_response),
    }
    if isinstance(extra, dict) and extra:
        record["extra"] = extra

    base = str(provider or "provider").lower().strip() or "provider"
    contracts_path = _contracts_dir()
    jsonl_path = os.path.join(contracts_path, f"{base}_violations.jsonl")
    summary_path = os.path.join(contracts_path, f"{base}_violations_summary.json")

    with _LOCK:
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        summary = _safe_json_load(summary_path)
        summary.setdefault("provider", base)
        summary["updated_at"] = ts
        summary["total_violations"] = int(summary.get("total_violations", 0)) + 1

        by_contract = summary.setdefault("by_contract", {})
        by_contract[record["contract_name"]] = int(by_contract.get(record["contract_name"], 0)) + 1

        by_error_code = summary.setdefault("by_error_code", {})
        by_error_code[error_code] = int(by_error_code.get(error_code, 0)) + 1

        by_model = summary.setdefault("by_model", {})
        by_model[record["model"]] = int(by_model.get(record["model"], 0)) + 1

        _safe_json_dump(summary_path, summary)
