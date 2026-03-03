from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .base import SearchResultItem


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


def normalize_url(url: str, strip_tracking_params: bool = True) -> str:
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
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except Exception:
        return value


def canonical_key(url: str) -> str:
    normalized = normalize_url(url, strip_tracking_params=True)
    if not normalized:
        return ""
    parts = urlsplit(normalized)
    host = (parts.netloc or "").lower().split(":", 1)[0]
    path = (parts.path or "/").rstrip("/") or "/"
    return f"{host}{path}"


def host_from_url(url: str) -> str:
    try:
        return (urlsplit(url).netloc or "").lower().split(":", 1)[0]
    except Exception:
        return ""


def host_matches_domain(host: str, domain: str) -> bool:
    if host == domain:
        return True
    return host.endswith("." + domain)


def apply_domain_filters(
    results: Sequence[SearchResultItem],
    domains_allow: Sequence[str],
    domains_deny: Sequence[str],
) -> List[SearchResultItem]:
    allow = [str(d or "").strip().lower() for d in domains_allow if str(d or "").strip()]
    deny = [str(d or "").strip().lower() for d in domains_deny if str(d or "").strip()]
    filtered: List[SearchResultItem] = []
    for item in results:
        host = host_from_url(item.url)
        if not host:
            continue
        if allow and not any(host_matches_domain(host, dom) for dom in allow):
            continue
        if deny and any(host_matches_domain(host, dom) for dom in deny):
            continue
        filtered.append(item)
    return filtered


def dedupe_results(results: Sequence[SearchResultItem]) -> List[SearchResultItem]:
    deduped: List[SearchResultItem] = []
    seen = set()
    for item in results:
        key = canonical_key(item.url)
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        item.url = normalize_url(item.url, strip_tracking_params=True)
        deduped.append(item)
    return deduped


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]{2,}", str(text or "").lower())


def _safe_parse_date(value: Optional[str]) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(raw[:-1] + "+00:00")
    if len(raw) == 10 and raw.count("-") == 2:
        candidates.append(raw + "T00:00:00+00:00")
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def score_result(
    item: SearchResultItem,
    *,
    query: str,
    provider_weight: float,
    recency_days: int,
) -> float:
    query_tokens = set(_tokenize(query))
    hay_tokens = set(_tokenize(f"{item.title} {item.snippet}"))

    overlap = 0.0
    if query_tokens:
        overlap = len(query_tokens.intersection(hay_tokens)) / max(1, len(query_tokens))

    freshness = 0.0
    if recency_days > 0:
        dt = _safe_parse_date(item.published_at)
        if dt is not None:
            age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
            freshness = max(0.0, 1.0 - (age_days / float(max(1, recency_days))))

    score = 0.55 * overlap + 0.30 * max(0.0, min(1.0, provider_weight)) + 0.15 * freshness
    return max(0.0, min(1.0, score))


def cut_results(results: Sequence[SearchResultItem], limit: int) -> List[SearchResultItem]:
    out = list(results)[: max(1, int(limit or 1))]
    for idx, item in enumerate(out, start=1):
        item.rank = idx
    return out


def recency_threshold(recency_days: int) -> Optional[datetime]:
    if int(recency_days or 0) <= 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=int(recency_days))


def merge_warnings(*warning_lists: Iterable[str]) -> List[str]:
    merged: List[str] = []
    for lst in warning_lists:
        for item in lst:
            msg = str(item or "").strip()
            if msg and msg not in merged:
                merged.append(msg)
    return merged
