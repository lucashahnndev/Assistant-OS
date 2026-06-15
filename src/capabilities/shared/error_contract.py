import time
from typing import Any, Dict, List, Optional


def now_perf() -> float:
    return time.perf_counter()


def elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def base_envelope(
    *,
    ok: bool,
    provider: str,
    elapsed: int,
    warnings: Optional[List[str]] = None,
    status_code: Optional[int] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    retryable: bool = False,
    status: Optional[str] = None,
    reason: Optional[str] = None,
    result_summary: Optional[str] = None,
    structured_result: Optional[Any] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None,
    attachment_delivery: Optional[Dict[str, Any]] = None,
    freshness: Optional[Dict[str, Any]] = None,
    truncated: bool = False,
    requires_followup: bool = False,
    next_step_context: Optional[Dict[str, Any]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resolved_status = str(status or ("success" if ok else "error")).strip().lower()
    resolved_reason = reason if reason is not None else (error_code if error_code is not None else error_message)
    resolved_result_summary = result_summary if result_summary is not None else ("" if ok else str(error_message or ""))
    payload: Dict[str, Any] = {
        "ok": bool(ok),
        "success": bool(ok),
        "status": resolved_status,
        "provider": str(provider or ""),
        "error_code": error_code,
        "error_message": error_message,
        "retryable": bool(retryable),
        "status_code": status_code,
        "elapsed_ms": int(max(0, elapsed)),
        "warnings": list(warnings or []),
        "reason": resolved_reason,
        "result_summary": resolved_result_summary,
        "structured_result": structured_result if structured_result is not None else {},
        "artifacts": list(artifacts or []),
        "attachment_delivery": dict(attachment_delivery or {"status": "none", "confirmed": False}),
        "freshness": dict(freshness or {"status": "unknown"}),
        "truncated": bool(truncated),
        "requires_followup": bool(requires_followup),
        "next_step_context": dict(next_step_context or {}),
        "diagnostics": dict(diagnostics or {}),
    }
    # Compatibility aliases used by legacy callers.
    payload["error"] = error_code
    payload["message"] = error_message
    return payload


def success_envelope(
    *,
    provider: str,
    elapsed: int,
    warnings: Optional[List[str]] = None,
    status_code: Optional[int] = None,
    status: Optional[str] = None,
    reason: Optional[str] = None,
    result_summary: Optional[str] = None,
    structured_result: Optional[Any] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None,
    attachment_delivery: Optional[Dict[str, Any]] = None,
    freshness: Optional[Dict[str, Any]] = None,
    truncated: bool = False,
    requires_followup: bool = False,
    next_step_context: Optional[Dict[str, Any]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return base_envelope(
        ok=True,
        provider=provider,
        elapsed=elapsed,
        warnings=warnings,
        status_code=status_code,
        status=status,
        reason=reason,
        result_summary=result_summary,
        structured_result=structured_result,
        artifacts=artifacts,
        attachment_delivery=attachment_delivery,
        freshness=freshness,
        truncated=truncated,
        requires_followup=requires_followup,
        next_step_context=next_step_context,
        diagnostics=diagnostics,
        retryable=False,
        error_code=None,
        error_message=None,
    )


def error_envelope(
    *,
    provider: str,
    error_code: str,
    error_message: str,
    retryable: bool,
    elapsed: int,
    warnings: Optional[List[str]] = None,
    status_code: Optional[int] = None,
    status: Optional[str] = None,
    reason: Optional[str] = None,
    result_summary: Optional[str] = None,
    structured_result: Optional[Any] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None,
    attachment_delivery: Optional[Dict[str, Any]] = None,
    freshness: Optional[Dict[str, Any]] = None,
    truncated: bool = False,
    requires_followup: bool = False,
    next_step_context: Optional[Dict[str, Any]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return base_envelope(
        ok=False,
        provider=provider,
        elapsed=elapsed,
        warnings=warnings,
        status_code=status_code,
        error_code=error_code,
        error_message=error_message,
        retryable=retryable,
        status=status,
        reason=reason,
        result_summary=result_summary,
        structured_result=structured_result,
        artifacts=artifacts,
        attachment_delivery=attachment_delivery,
        freshness=freshness,
        truncated=truncated,
        requires_followup=requires_followup,
        next_step_context=next_step_context,
        diagnostics=diagnostics,
    )
