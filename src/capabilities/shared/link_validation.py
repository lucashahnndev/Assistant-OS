from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests


_BROKEN_STATUS_CODES = {400, 404, 410, 414, 451}
_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_RESTRICTED_STATUS_CODES = {401, 403}


@dataclass(slots=True)
class LinkValidationResult:
    ok: bool
    status: str
    reason: str
    url: str = ""
    final_url: str = ""
    status_code: Optional[int] = None
    retryable: bool = False
    method: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _normalize_url(url: str) -> str:
    return str(url or "").strip()


def _looks_like_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _build_headers() -> Dict[str, str]:
    return {
        "User-Agent": "Assistant-OS/1.0 (+https://github.com/openai)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def validate_media_link(url: str, *, timeout: float = 4.0) -> LinkValidationResult:
    normalized = _normalize_url(url)
    if not normalized or not _looks_like_url(normalized):
        return LinkValidationResult(
            ok=False,
            status="invalid_url",
            reason="URL inválida ou ausente.",
            url=normalized,
            retryable=False,
        )

    last_error: Optional[str] = None
    last_status_code: Optional[int] = None
    last_final_url = normalized

    for method in ("HEAD", "GET"):
        try:
            response = requests.request(
                method,
                normalized,
                allow_redirects=True,
                timeout=timeout,
                headers=_build_headers(),
                stream=(method == "GET"),
            )
            last_status_code = int(getattr(response, "status_code", 0) or 0) or None
            last_final_url = str(getattr(response, "url", normalized) or normalized)

            if last_status_code is not None and 200 <= last_status_code < 400:
                return LinkValidationResult(
                    ok=True,
                    status="valid",
                    reason="Link confirmado com sucesso.",
                    url=normalized,
                    final_url=last_final_url,
                    status_code=last_status_code,
                    retryable=False,
                    method=method,
                )

            if last_status_code in _BROKEN_STATUS_CODES:
                return LinkValidationResult(
                    ok=False,
                    status="broken",
                    reason=f"Link retornou HTTP {last_status_code}.",
                    url=normalized,
                    final_url=last_final_url,
                    status_code=last_status_code,
                    retryable=False,
                    method=method,
                )

            if last_status_code in _RETRYABLE_STATUS_CODES:
                return LinkValidationResult(
                    ok=False,
                    status="error",
                    reason=f"Link temporariamente indisponível (HTTP {last_status_code}).",
                    url=normalized,
                    final_url=last_final_url,
                    status_code=last_status_code,
                    retryable=True,
                    method=method,
                )

            if last_status_code in _RESTRICTED_STATUS_CODES:
                last_error = f"Acesso restrito ao link (HTTP {last_status_code})."
                continue

            if last_status_code is not None:
                last_error = f"Resposta inesperada do link (HTTP {last_status_code})."
                continue
        except requests.RequestException as exc:
            last_error = str(exc)
            last_status_code = None
            continue

    if last_error and "Acesso restrito" in last_error:
        return LinkValidationResult(
            ok=False,
            status="restricted",
            reason=last_error,
            url=normalized,
            final_url=last_final_url,
            status_code=last_status_code,
            retryable=False,
            method="GET",
        )

    return LinkValidationResult(
        ok=False,
        status="error",
        reason=last_error or "Não foi possível validar o link.",
        url=normalized,
        final_url=last_final_url,
        status_code=last_status_code,
        retryable=True,
        method="GET",
    )


def validate_media_results(
    results: List[Dict[str, Any]],
    *,
    timeout: float = 4.0,
    preferred_statuses: Tuple[str, ...] = ("valid", "restricted"),
) -> Dict[str, Any]:
    validated: List[Dict[str, Any]] = []
    chosen_valid: Optional[Dict[str, Any]] = None
    chosen_restricted: Optional[Dict[str, Any]] = None
    failures: List[Dict[str, Any]] = []

    for item in results:
        entry = dict(item)
        outcome = validate_media_link(entry.get("url", ""), timeout=timeout)
        entry["link_validation"] = outcome.to_dict()
        validated.append(entry)
        if outcome.ok and outcome.status == "valid" and chosen_valid is None:
            chosen_valid = entry
        elif outcome.status == "restricted" and chosen_restricted is None:
            chosen_restricted = entry
        elif not outcome.ok:
            failures.append(
                {
                    "url": outcome.url,
                    "status": outcome.status,
                    "reason": outcome.reason,
                    "status_code": outcome.status_code,
                    "retryable": outcome.retryable,
                }
            )

    return {
        "results": validated,
        "best": chosen_valid or chosen_restricted,
        "failures": failures,
        "has_valid": any(item.get("link_validation", {}).get("status") == "valid" for item in validated),
        "has_restricted": any(item.get("link_validation", {}).get("status") == "restricted" for item in validated),
    }
