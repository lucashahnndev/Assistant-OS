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
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": bool(ok),
        "status": "success" if ok else "error",
        "provider": str(provider or ""),
        "error_code": error_code,
        "error_message": error_message,
        "retryable": bool(retryable),
        "status_code": status_code,
        "elapsed_ms": int(max(0, elapsed)),
        "warnings": list(warnings or []),
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
) -> Dict[str, Any]:
    return base_envelope(
        ok=True,
        provider=provider,
        elapsed=elapsed,
        warnings=warnings,
        status_code=status_code,
        error_code=None,
        error_message=None,
        retryable=False,
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
    )
