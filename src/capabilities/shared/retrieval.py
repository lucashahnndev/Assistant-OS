import copy
import hashlib
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .chunking import normalize_whitespace

logger = logging.getLogger("WebRetrieval")

try:
    import trafilatura
except Exception:  # pragma: no cover - optional dependency
    trafilatura = None  # type: ignore

try:
    from readability import Document
except Exception:  # pragma: no cover - optional dependency
    Document = None  # type: ignore


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
}

_BUCKET_LOCK = threading.Lock()
_BUCKETS: Dict[str, Dict[str, float]] = {}

_CACHE_LOCK = threading.Lock()
_READ_CACHE: Dict[str, Dict[str, Any]] = {}


def clamp_max_chars(value: Any, default: int = 12000) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(100, min(n, 50000))


def clamp_max_bytes(value: Any, default: int = 2_000_000) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(128, min(n, 25_000_000))


def clamp_timeout_ms(value: Any, default: int = 10000) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(500, min(n, 120000))


def clamp_retries(value: Any, default: int = 1) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(0, min(n, 3))


def clamp_rate_limit(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except Exception:
        n = default
    return max(0.0, min(n, 50.0))


def clamp_cache_ttl(value: Any, default: int = 0) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(0, min(n, 3600))


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _telemetry_enabled(value: Any) -> bool:
    return bool(value)


def _telemetry_level(value: Any) -> str:
    level = str(value or "basic").strip().lower()
    return level if level in {"basic", "verbose"} else "basic"


def _emit_telemetry(event: str, *, enabled: bool, level: str, payload: Dict[str, Any]) -> None:
    if not _telemetry_enabled(enabled):
        return
    compact = dict(payload)
    compact["event"] = event
    compact["level"] = _telemetry_level(level)
    try:
        logger.info(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        logger.info("%s %s", event, compact)


def _normalize_url(url: str, strip_tracking_params: bool) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        query = parts.query
        if strip_tracking_params and query:
            pairs = parse_qsl(query, keep_blank_values=True)
            filtered = [(k, v) for (k, v) in pairs if k.lower() not in _TRACKING_PARAMS]
            query = urlencode(filtered, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except Exception:
        return value


def _cache_key(*, url: str, mode: str, max_chars: int, max_bytes: int, strip_tracking_params: bool) -> str:
    return f"{url}|{mode}|{max_chars}|{max_bytes}|{int(bool(strip_tracking_params))}"


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _CACHE_LOCK:
        entry = _READ_CACHE.get(key)
        if not entry:
            return None
        if float(entry.get("exp", 0.0)) <= now:
            _READ_CACHE.pop(key, None)
            return None
        payload = entry.get("payload")
        if isinstance(payload, dict):
            cached = copy.deepcopy(payload)
            warnings = cached.get("warnings") if isinstance(cached.get("warnings"), list) else []
            warnings.append("cache_hit")
            cached["warnings"] = warnings
            return cached
    return None


def _cache_set(key: str, payload: Dict[str, Any], ttl_sec: int) -> None:
    if ttl_sec <= 0 or not isinstance(payload, dict):
        return
    with _CACHE_LOCK:
        if len(_READ_CACHE) > 512:
            # simple sweep of expired entries
            now = time.time()
            for k in list(_READ_CACHE.keys())[:128]:
                if float(_READ_CACHE.get(k, {}).get("exp", 0.0)) <= now:
                    _READ_CACHE.pop(k, None)
        _READ_CACHE[key] = {
            "exp": time.time() + ttl_sec,
            "payload": copy.deepcopy(payload),
        }


def _acquire_host_token(host: str, rate_limit_per_host: float) -> bool:
    rate = clamp_rate_limit(rate_limit_per_host, default=0.0)
    if rate <= 0:
        return True
    now = time.time()
    cap = max(1.0, rate)

    with _BUCKET_LOCK:
        state = _BUCKETS.get(host)
        if not state:
            _BUCKETS[host] = {"tokens": cap - 1.0, "last": now}
            return True

        tokens = float(state.get("tokens", cap))
        last = float(state.get("last", now))
        tokens = min(cap, tokens + max(0.0, now - last) * rate)
        if tokens < 1.0:
            state["tokens"] = tokens
            state["last"] = now
            return False

        state["tokens"] = tokens - 1.0
        state["last"] = now
        return True


def _extract_canonical_and_title(
    html: str,
    final_url: str,
    strip_tracking_params: bool,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    soup = BeautifulSoup(html or "", "html.parser")

    canonical_url: Optional[str] = None
    canonical = soup.find("link", rel=lambda x: x and "canonical" in str(x).lower())
    if canonical and canonical.get("href"):
        canonical_url = urljoin(final_url, str(canonical.get("href")).strip())
        canonical_url = _normalize_url(canonical_url, strip_tracking_params)

    title: Optional[str] = None
    if soup.title and soup.title.string:
        title = normalize_whitespace(soup.title.string)

    language: Optional[str] = None
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        language = normalize_whitespace(html_tag.get("lang")).split(" ")[0] or None

    return canonical_url, title, language


def _strip_noise_tags(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in ["script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "form"]:
        for node in soup.find_all(tag):
            node.decompose()
    return soup


def _extract_main_html(html: str) -> str:
    if trafilatura is not None:
        try:
            extracted = trafilatura.extract(
                html,
                output_format="markdown",
                include_comments=False,
                include_tables=False,
                favor_recall=True,
                deduplicate=True,
            )
            if extracted and normalize_whitespace(extracted):
                return str(extracted)
        except Exception:
            pass

    if Document is not None:
        try:
            summary_html = Document(html).summary()
            soup = BeautifulSoup(summary_html, "html.parser")
            text = normalize_whitespace(soup.get_text(" ", strip=True))
            if text:
                return text
        except Exception:
            pass

    soup = BeautifulSoup(html, "html.parser")
    _strip_noise_tags(soup)
    body = soup.body or soup
    return normalize_whitespace(body.get_text(" ", strip=True))


def _extract_all_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    _strip_noise_tags(soup)
    body = soup.body or soup
    return normalize_whitespace(body.get_text(" ", strip=True))


def _base_result(
    *,
    url: str,
    final_url: Optional[str],
    status_code: Optional[int],
    elapsed_ms: int,
    content_type: Optional[str],
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    normalized_final = _normalize_url(final_url or url, strip_tracking_params=False)
    return {
        "provider": "web.retrieve",
        "url": url,
        "final_url": normalized_final,
        "canonical_url": normalized_final,
        "title": None,
        "status_code": status_code,
        "content_type": content_type,
        "elapsed_ms": elapsed_ms,
        "warnings": warnings or [],
    }


def _error_payload(
    *,
    url: str,
    final_url: Optional[str],
    error_code: str,
    error_message: str,
    retryable: bool,
    elapsed_ms: int,
    status_code: Optional[int] = None,
    content_type: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload = {
        "ok": False,
        "status": "error",
        "error_code": error_code,
        "error_message": error_message,
        "retryable": bool(retryable),
        **_base_result(
            url=url,
            final_url=final_url,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            content_type=content_type,
            warnings=warnings,
        ),
        "text_md": "",
        "language": None,
    }
    # compatibility aliases
    payload["error"] = error_code
    payload["message"] = error_message
    return payload


def _success_payload(
    *,
    url: str,
    final_url: str,
    canonical_url: Optional[str],
    title: Optional[str],
    status_code: int,
    content_type: str,
    elapsed_ms: int,
    text_md: str,
    language: Optional[str],
    warnings: List[str],
) -> Dict[str, Any]:
    payload = {
        "ok": True,
        "status": "success",
        "error_code": None,
        "error_message": None,
        "retryable": False,
        **_base_result(
            url=url,
            final_url=final_url,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            content_type=content_type,
            warnings=warnings,
        ),
        "canonical_url": canonical_url or final_url,
        "title": title,
        "text_md": text_md,
        "language": language,
    }
    return payload


def _read_response_text_with_limit(resp: httpx.Response, max_bytes: int) -> bytes:
    content_length = resp.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise ValueError("TOO_LARGE")
        except Exception:
            pass

    total = 0
    chunks: List[bytes] = []
    for chunk in resp.iter_bytes():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_bytes(raw: bytes, encoding_hint: Optional[str]) -> str:
    enc = (encoding_hint or "").strip()
    if enc:
        try:
            return raw.decode(enc, errors="replace")
        except Exception:
            pass
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return raw.decode(errors="replace")


def _is_supported_content(content_type: str) -> bool:
    ct = (content_type or "").lower()
    if ct.startswith("text/html"):
        return True
    if ct.startswith("application/xhtml+xml"):
        return True
    if ct.startswith("text/plain"):
        return True
    if ct.startswith("application/json"):
        return True
    return False


def _is_html_content(content_type: str, body_text: str) -> bool:
    ct = (content_type or "").lower()
    if ct.startswith("text/html") or ct.startswith("application/xhtml+xml"):
        return True
    probe = (body_text or "")[:600].lower()
    return "<html" in probe or "<body" in probe


def _is_json_content(content_type: str, body_text: str) -> bool:
    ct = (content_type or "").lower()
    if ct.startswith("application/json"):
        return True
    probe = (body_text or "").strip()
    return probe.startswith("{") or probe.startswith("[")


def _should_retry_http(status_code: int) -> bool:
    return status_code in {408, 425, 429, 500, 502, 503, 504}


def _check_robots(
    *,
    client: httpx.Client,
    url: str,
    respect_robots: bool,
) -> Tuple[bool, Optional[str]]:
    if not respect_robots:
        return True, None
    try:
        parsed = urlsplit(url)
        if not parsed.scheme or not parsed.netloc:
            return True, None
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        resp = client.get(robots_url)
        if resp.status_code >= 400:
            return True, None
        text = resp.text or ""
        if not text.strip():
            return True, None

        # Simple user-agent parser (allow by default, deny if matching rule blocks path).
        current_agents: List[str] = []
        disallow_rules: List[str] = []
        path = parsed.path or "/"
        for line in text.splitlines():
            raw = line.split("#", 1)[0].strip()
            if not raw or ":" not in raw:
                continue
            key, val = raw.split(":", 1)
            key = key.strip().lower()
            val = val.strip()
            if key == "user-agent":
                current_agents = [v.strip().lower() for v in val.split()] if val else []
            elif key == "disallow":
                if not current_agents:
                    continue
                if "*" in current_agents or any(a in USER_AGENT.lower() for a in current_agents):
                    disallow_rules.append(val)

        for rule in disallow_rules:
            if not rule:
                continue
            if rule == "/" or path.startswith(rule):
                return False, None
        return True, None
    except Exception as e:
        return True, f"robots_check_failed:{e}"


def _fetch_raw(
    *,
    url: str,
    timeout_ms: int,
    connect_timeout_ms: int,
    read_timeout_ms: int,
    retries: int,
    max_bytes: int,
    strip_tracking_params: bool,
    respect_robots: bool,
    rate_limit_per_host: float,
    telemetry_enabled: bool = False,
    telemetry_level: str = "basic",
) -> Dict[str, Any]:
    started = time.perf_counter()
    raw_url = str(url or "").strip()
    if not raw_url:
        return _error_payload(
            url="",
            final_url=None,
            error_code="MISSING_URL",
            error_message="Parameter 'url' is required.",
            retryable=False,
            elapsed_ms=0,
        )

    normalized_input_url = _normalize_url(raw_url, strip_tracking_params)
    host = (urlsplit(normalized_input_url).netloc or "").lower()
    if host and not _acquire_host_token(host, rate_limit_per_host):
        wait_ms = int(1000.0 / max(0.001, clamp_rate_limit(rate_limit_per_host, default=0.0)))
        _emit_telemetry(
            "EVT:RETRIEVE:RATE_LIMIT",
            enabled=telemetry_enabled,
            level=telemetry_level,
            payload={"host": host, "wait_ms": wait_ms},
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return _error_payload(
            url=raw_url,
            final_url=normalized_input_url,
            error_code="RATE_LIMITED",
            error_message=f"Local host rate limit exceeded for {host}.",
            retryable=True,
            elapsed_ms=elapsed_ms,
        )

    timeout = httpx.Timeout(
        timeout_ms / 1000.0,
        connect=connect_timeout_ms / 1000.0,
        read=read_timeout_ms / 1000.0,
    )

    last_exception: Optional[Exception] = None
    warnings: List[str] = []

    for attempt in range(retries + 1):
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=timeout,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.8,*/*;q=0.5",
                    "Accept-Encoding": "gzip, deflate, br",
                },
            ) as client:
                allowed, robots_warning = _check_robots(client=client, url=normalized_input_url, respect_robots=respect_robots)
                if robots_warning:
                    warnings.append(robots_warning)
                if not allowed:
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    return _error_payload(
                        url=raw_url,
                        final_url=normalized_input_url,
                        error_code="ROBOTS_DENIED",
                        error_message="Access denied by robots.txt policy.",
                        retryable=False,
                        elapsed_ms=elapsed_ms,
                        warnings=warnings,
                    )

                with client.stream("GET", normalized_input_url) as resp:
                    status_code = int(resp.status_code)
                    content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                    final_url = _normalize_url(str(resp.url), strip_tracking_params)

                    if status_code == 429:
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        _emit_telemetry(
                            "EVT:RETRIEVE:FETCH",
                            enabled=telemetry_enabled,
                            level=telemetry_level,
                            payload={
                                "url": raw_url,
                                "status_code": status_code,
                                "elapsed_ms": elapsed_ms,
                                "bytes": 0,
                                "content_type": content_type,
                            },
                        )
                        return _error_payload(
                            url=raw_url,
                            final_url=final_url,
                            error_code="RATE_LIMITED",
                            error_message="HTTP 429 Too Many Requests",
                            retryable=True,
                            elapsed_ms=elapsed_ms,
                            status_code=status_code,
                            content_type=content_type,
                            warnings=warnings,
                        )

                    if status_code >= 400:
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        _emit_telemetry(
                            "EVT:RETRIEVE:FETCH",
                            enabled=telemetry_enabled,
                            level=telemetry_level,
                            payload={
                                "url": raw_url,
                                "status_code": status_code,
                                "elapsed_ms": elapsed_ms,
                                "bytes": 0,
                                "content_type": content_type,
                            },
                        )
                        return _error_payload(
                            url=raw_url,
                            final_url=final_url,
                            error_code="HTTP_ERROR",
                            error_message=f"HTTP {status_code}",
                            retryable=_should_retry_http(status_code),
                            elapsed_ms=elapsed_ms,
                            status_code=status_code,
                            content_type=content_type,
                            warnings=warnings,
                        )

                    if content_type.startswith("application/pdf"):
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        _emit_telemetry(
                            "EVT:RETRIEVE:FETCH",
                            enabled=telemetry_enabled,
                            level=telemetry_level,
                            payload={
                                "url": raw_url,
                                "status_code": status_code,
                                "elapsed_ms": elapsed_ms,
                                "bytes": 0,
                                "content_type": content_type,
                            },
                        )
                        return _error_payload(
                            url=raw_url,
                            final_url=final_url,
                            error_code="UNSUPPORTED_CONTENT_TYPE",
                            error_message="Unsupported content type: application/pdf",
                            retryable=False,
                            elapsed_ms=elapsed_ms,
                            status_code=status_code,
                            content_type=content_type,
                            warnings=warnings,
                        )

                    if not _is_supported_content(content_type):
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        _emit_telemetry(
                            "EVT:RETRIEVE:FETCH",
                            enabled=telemetry_enabled,
                            level=telemetry_level,
                            payload={
                                "url": raw_url,
                                "status_code": status_code,
                                "elapsed_ms": elapsed_ms,
                                "bytes": 0,
                                "content_type": content_type,
                            },
                        )
                        return _error_payload(
                            url=raw_url,
                            final_url=final_url,
                            error_code="UNSUPPORTED_CONTENT_TYPE",
                            error_message=f"Unsupported content type: {content_type or 'unknown'}",
                            retryable=False,
                            elapsed_ms=elapsed_ms,
                            status_code=status_code,
                            content_type=content_type,
                            warnings=warnings,
                        )

                    try:
                        body_bytes = _read_response_text_with_limit(resp, max_bytes=max_bytes)
                    except ValueError:
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        _emit_telemetry(
                            "EVT:RETRIEVE:FETCH",
                            enabled=telemetry_enabled,
                            level=telemetry_level,
                            payload={
                                "url": raw_url,
                                "status_code": status_code,
                                "elapsed_ms": elapsed_ms,
                                "bytes": max_bytes,
                                "content_type": content_type,
                            },
                        )
                        return _error_payload(
                            url=raw_url,
                            final_url=final_url,
                            error_code="TOO_LARGE",
                            error_message=f"Response exceeded max_bytes={max_bytes}",
                            retryable=False,
                            elapsed_ms=elapsed_ms,
                            status_code=status_code,
                            content_type=content_type,
                            warnings=warnings,
                        )

                    body_text = _decode_bytes(body_bytes, resp.encoding)
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    redirects_count = len(getattr(resp, "history", []) or [])
                    _emit_telemetry(
                        "EVT:RETRIEVE:FETCH",
                        enabled=telemetry_enabled,
                        level=telemetry_level,
                        payload={
                            "url": raw_url,
                            "status_code": status_code,
                            "elapsed_ms": elapsed_ms,
                            "bytes": len(body_bytes),
                            "content_type": content_type,
                            **(
                                {
                                    "canonical_url": final_url,
                                    "redirects_count": redirects_count,
                                }
                                if _telemetry_level(telemetry_level) == "verbose"
                                else {}
                            ),
                        },
                    )
                    return {
                        "ok": True,
                        "status": "success",
                        "provider": "web.retrieve",
                        "url": raw_url,
                        "final_url": final_url,
                        "status_code": status_code,
                        "content_type": content_type,
                        "elapsed_ms": elapsed_ms,
                        "warnings": warnings,
                        "body_text": body_text,
                        "bytes_downloaded": len(body_bytes),
                        "redirects_count": redirects_count,
                        "content_language": normalize_whitespace(resp.headers.get("content-language") or "") or None,
                    }

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException) as e:
            last_exception = e
            if attempt < retries:
                continue
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return _error_payload(
                url=raw_url,
                final_url=normalized_input_url,
                error_code="TIMEOUT",
                error_message="Timed out while fetching URL.",
                retryable=True,
                elapsed_ms=elapsed_ms,
                warnings=warnings,
            )
        except httpx.ConnectError as e:
            last_exception = e
            if attempt < retries:
                continue
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            message = str(e)
            lowered = message.lower()
            is_dns = (
                "name or service not known" in lowered
                or "temporary failure in name resolution" in lowered
                or "nodename nor servname provided" in lowered
                or "no address associated with hostname" in lowered
            )
            return _error_payload(
                url=raw_url,
                final_url=normalized_input_url,
                error_code="DNS_ERROR" if is_dns else "CONNECTION_ERROR",
                error_message=message or "Failed to connect to host.",
                retryable=True,
                elapsed_ms=elapsed_ms,
                warnings=warnings,
            )
        except httpx.RequestError as e:
            last_exception = e
            if attempt < retries:
                continue
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return _error_payload(
                url=raw_url,
                final_url=normalized_input_url,
                error_code="CONNECTION_ERROR",
                error_message=str(e),
                retryable=True,
                elapsed_ms=elapsed_ms,
                warnings=warnings,
            )
        except Exception as e:
            last_exception = e
            break

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return _error_payload(
        url=raw_url,
        final_url=normalized_input_url,
        error_code="FETCH_ERROR",
        error_message=str(last_exception) if last_exception else "Unknown fetch error.",
        retryable=True,
        elapsed_ms=elapsed_ms,
    )


def fetch_and_read(
    *,
    url: str,
    mode: str = "auto",
    max_chars: int = 12000,
    timeout_ms: int = 10000,
    retries: int = 1,
    connect_timeout_ms: Optional[int] = None,
    read_timeout_ms: Optional[int] = None,
    max_bytes: int = 2_000_000,
    strip_tracking_params: bool = True,
    respect_robots: bool = False,
    rate_limit_per_host: float = 0.0,
    cache_ttl_sec: int = 0,
    telemetry_enabled: bool = False,
    telemetry_level: str = "basic",
) -> Dict[str, Any]:
    """Deterministic web retrieval without LLM."""
    raw_url = str(url or "").strip()
    if not raw_url:
        return _error_payload(
            url="",
            final_url=None,
            error_code="MISSING_URL",
            error_message="Parameter 'url' is required.",
            retryable=False,
            elapsed_ms=0,
        )

    selected_mode = str(mode or "auto").strip().lower()
    if selected_mode not in {"auto", "main", "all"}:
        selected_mode = "auto"

    max_chars = clamp_max_chars(max_chars, default=12000)
    timeout_ms = clamp_timeout_ms(timeout_ms, default=10000)
    connect_timeout_ms = clamp_timeout_ms(connect_timeout_ms if connect_timeout_ms is not None else timeout_ms, default=timeout_ms)
    read_timeout_ms = clamp_timeout_ms(read_timeout_ms if read_timeout_ms is not None else timeout_ms, default=timeout_ms)
    retries = clamp_retries(retries, default=1)
    max_bytes = clamp_max_bytes(max_bytes, default=2_000_000)
    cache_ttl_sec = clamp_cache_ttl(cache_ttl_sec, default=0)

    normalized = _normalize_url(raw_url, strip_tracking_params)
    key = _cache_key(
        url=normalized,
        mode=selected_mode,
        max_chars=max_chars,
        max_bytes=max_bytes,
        strip_tracking_params=strip_tracking_params,
    )
    cached = _cache_get(key) if cache_ttl_sec > 0 else None
    if cached:
        _emit_telemetry(
            "EVT:RETRIEVE:CACHE",
            enabled=telemetry_enabled,
            level=telemetry_level,
            payload={
                "status": "hit",
                "key_prefix": hashlib.sha1(key.encode("utf-8")).hexdigest()[:12],
                "ttl_s": cache_ttl_sec,
            },
        )
        return cached
    if cache_ttl_sec > 0:
        _emit_telemetry(
            "EVT:RETRIEVE:CACHE",
            enabled=telemetry_enabled,
            level=telemetry_level,
            payload={
                "status": "miss",
                "key_prefix": hashlib.sha1(key.encode("utf-8")).hexdigest()[:12],
                "ttl_s": cache_ttl_sec,
            },
        )

    fetch_result = _fetch_raw(
        url=raw_url,
        timeout_ms=timeout_ms,
        connect_timeout_ms=connect_timeout_ms,
        read_timeout_ms=read_timeout_ms,
        retries=retries,
        max_bytes=max_bytes,
        strip_tracking_params=strip_tracking_params,
        respect_robots=respect_robots,
        rate_limit_per_host=rate_limit_per_host,
        telemetry_enabled=telemetry_enabled,
        telemetry_level=telemetry_level,
    )

    if not fetch_result.get("ok"):
        logger.info(
            "web.retrieve.read url=%s status_code=%s content_type=%s chars_out=%s elapsed_ms=%s error_code=%s",
            raw_url,
            fetch_result.get("status_code"),
            fetch_result.get("content_type"),
            0,
            fetch_result.get("elapsed_ms"),
            fetch_result.get("error_code"),
        )
        return fetch_result

    body_text = str(fetch_result.get("body_text") or "")
    content_type = str(fetch_result.get("content_type") or "").lower()
    final_url = str(fetch_result.get("final_url") or raw_url)
    status_code = int(fetch_result.get("status_code") or 0)
    elapsed_ms = int(fetch_result.get("elapsed_ms") or 0)
    warnings = list(fetch_result.get("warnings") or [])

    canonical_url: Optional[str] = _normalize_url(final_url, strip_tracking_params)
    title: Optional[str] = final_url
    language: Optional[str] = fetch_result.get("content_language")

    looks_html = _is_html_content(content_type, body_text)
    parse_started = time.perf_counter()
    parser_used = "plain"
    try:
        if looks_html:
            extraction_mode = "main" if selected_mode == "auto" else selected_mode
            canonical_url, title, html_language = _extract_canonical_and_title(
                body_text,
                final_url,
                strip_tracking_params=strip_tracking_params,
            )
            if html_language:
                language = html_language
            extracted = _extract_main_html(body_text) if extraction_mode == "main" else _extract_all_html(body_text)
            parser_used = "trafilatura/readability/bs4" if extraction_mode == "main" else "bs4"
        elif _is_json_content(content_type, body_text):
            parsed = json.loads(body_text)
            extracted = json.dumps(parsed, ensure_ascii=False)
            parser_used = "json"
        else:
            extracted = normalize_whitespace(body_text)
            parser_used = "text"
    except Exception as e:
        payload = _error_payload(
            url=raw_url,
            final_url=final_url,
            error_code="PARSE_FAILED",
            error_message=str(e),
            retryable=False,
            elapsed_ms=elapsed_ms,
            status_code=status_code,
            content_type=content_type,
            warnings=warnings,
        )
        logger.info(
            "web.retrieve.read url=%s status_code=%s content_type=%s chars_out=%s elapsed_ms=%s error_code=%s",
            raw_url,
            status_code,
            content_type,
            0,
            elapsed_ms,
            payload.get("error_code"),
        )
        return payload

    extracted = normalize_whitespace(extracted)
    if not extracted:
        warnings.append("No meaningful text extracted from document.")

    text_md = truncate_text(extracted, max_chars)
    payload = _success_payload(
        url=raw_url,
        final_url=final_url,
        canonical_url=canonical_url,
        title=title,
        status_code=status_code,
        content_type=content_type,
        elapsed_ms=elapsed_ms,
        text_md=text_md,
        language=language,
        warnings=warnings,
    )
    parse_elapsed = int((time.perf_counter() - parse_started) * 1000)
    _emit_telemetry(
        "EVT:RETRIEVE:PARSE",
        enabled=telemetry_enabled,
        level=telemetry_level,
        payload={
            "parser_used": parser_used,
            "elapsed_ms": parse_elapsed,
            "text_len": len(text_md),
            **(
                {
                    "canonical_url": payload.get("canonical_url"),
                    "redirects_count": int(fetch_result.get("redirects_count") or 0),
                    "chunk_count": 0,
                }
                if _telemetry_level(telemetry_level) == "verbose"
                else {}
            ),
        },
    )

    logger.info(
        "web.retrieve.read url=%s status_code=%s content_type=%s chars_out=%s elapsed_ms=%s error_code=%s",
        raw_url,
        status_code,
        content_type,
        len(text_md),
        elapsed_ms,
        None,
    )

    if cache_ttl_sec > 0:
        _cache_set(key, payload, cache_ttl_sec)

    return payload


def extract_structured(
    *,
    url: str,
    schema: Any,
    max_chars: int = 12000,
    timeout_ms: int = 10000,
    retries: int = 1,
    connect_timeout_ms: Optional[int] = None,
    read_timeout_ms: Optional[int] = None,
    max_bytes: int = 2_000_000,
    strip_tracking_params: bool = True,
    respect_robots: bool = False,
    rate_limit_per_host: float = 0.0,
    telemetry_enabled: bool = False,
    telemetry_level: str = "basic",
) -> Dict[str, Any]:
    started = time.perf_counter()
    max_chars = clamp_max_chars(max_chars, default=12000)

    read_payload = fetch_and_read(
        url=url,
        mode="all",
        max_chars=max_chars,
        timeout_ms=timeout_ms,
        retries=retries,
        connect_timeout_ms=connect_timeout_ms,
        read_timeout_ms=read_timeout_ms,
        max_bytes=max_bytes,
        strip_tracking_params=strip_tracking_params,
        respect_robots=respect_robots,
        rate_limit_per_host=rate_limit_per_host,
        cache_ttl_sec=0,
        telemetry_enabled=telemetry_enabled,
        telemetry_level=telemetry_level,
    )

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if not read_payload.get("ok"):
        read_payload["elapsed_ms"] = max(elapsed_ms, int(read_payload.get("elapsed_ms") or 0))
        read_payload["data"] = {}
        read_payload.setdefault("warnings", [])
        return read_payload

    content_type = str(read_payload.get("content_type") or "")
    if "html" not in content_type and "xhtml" not in content_type:
        return {
            **_error_payload(
                url=str(read_payload.get("url") or url),
                final_url=str(read_payload.get("final_url") or read_payload.get("url") or url),
                error_code="UNSUPPORTED_CONTENT_TYPE",
                error_message=f"Structured extraction expects HTML content, got: {content_type or 'unknown'}",
                retryable=False,
                elapsed_ms=elapsed_ms,
                status_code=read_payload.get("status_code"),
                content_type=content_type,
            ),
            "data": {},
            "canonical_url": read_payload.get("canonical_url"),
            "title": read_payload.get("title"),
            "final_url": read_payload.get("final_url"),
        }

    warnings: List[str] = list(read_payload.get("warnings") or [])
    fields = schema if isinstance(schema, list) else []

    body_text = str(read_payload.get("text_md") or "")
    # For selector-level extraction try a raw HTML fetch for fidelity.
    raw_fetch = _fetch_raw(
        url=str(read_payload.get("final_url") or url),
        timeout_ms=clamp_timeout_ms(timeout_ms, default=10000),
        connect_timeout_ms=clamp_timeout_ms(connect_timeout_ms if connect_timeout_ms is not None else timeout_ms, default=timeout_ms),
        read_timeout_ms=clamp_timeout_ms(read_timeout_ms if read_timeout_ms is not None else timeout_ms, default=timeout_ms),
        retries=clamp_retries(retries, default=1),
        max_bytes=clamp_max_bytes(max_bytes, default=2_000_000),
        strip_tracking_params=strip_tracking_params,
        respect_robots=respect_robots,
        rate_limit_per_host=rate_limit_per_host,
        telemetry_enabled=telemetry_enabled,
        telemetry_level=telemetry_level,
    )
    if isinstance(raw_fetch, dict) and raw_fetch.get("ok") and isinstance(raw_fetch.get("body_text"), str):
        body_text = str(raw_fetch.get("body_text") or body_text)

    soup = BeautifulSoup(body_text, "html.parser")
    extracted_data: Dict[str, Any] = {}

    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "").strip()
        if not name:
            continue

        selector = field.get("selector")
        attr = field.get("attr")
        regex = field.get("regex")
        required = bool(field.get("required"))

        value: Optional[str] = None

        if isinstance(selector, str) and selector.strip():
            node = soup.select_one(selector.strip())
            if node is not None:
                if isinstance(attr, str) and attr.strip():
                    attr_val = node.get(attr.strip())
                    value = normalize_whitespace(attr_val)
                else:
                    value = normalize_whitespace(node.get_text(" ", strip=True))

        if value is None and isinstance(regex, str) and regex.strip():
            try:
                match = re.search(regex.strip(), body_text, flags=re.IGNORECASE | re.MULTILINE)
                if match:
                    value = normalize_whitespace(match.group(1) if match.groups() else match.group(0))
            except re.error:
                warnings.append(f"Invalid regex for field '{name}'.")

        if value is None:
            value = ""

        extracted_data[name] = truncate_text(value, max_chars)
        if required and not extracted_data[name]:
            warnings.append(f"Required field missing: {name}")

    return {
        "ok": True,
        "status": "success",
        "provider": "web.retrieve",
        "url": read_payload.get("url"),
        "final_url": read_payload.get("final_url"),
        "canonical_url": read_payload.get("canonical_url"),
        "title": read_payload.get("title"),
        "status_code": read_payload.get("status_code"),
        "content_type": read_payload.get("content_type"),
        "elapsed_ms": elapsed_ms,
        "retryable": False,
        "error_code": None,
        "error_message": None,
        "data": extracted_data,
        "warnings": warnings,
    }
