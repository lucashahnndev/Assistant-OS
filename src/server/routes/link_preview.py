"""
Link Preview API endpoint.
Fetches OpenGraph metadata from URLs with SSRF protection and caching.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..auth import get_current_user
from ..core.models import User

import requests
import socket
import ipaddress
import time
import re
import html
import logging
from urllib.parse import urlparse
from threading import Lock

logger = logging.getLogger("LinkPreview")
router = APIRouter(prefix="/api", tags=["link_preview"])

# ── Cache ────────────────────────────────────────────────────────────────
_cache: dict = {}  # url -> { data, ts }
_cache_lock = Lock()
CACHE_TTL = 12 * 3600  # 12 hours
CACHE_MAX = 500

def _cache_get(url: str):
    with _cache_lock:
        entry = _cache.get(url)
        if entry and (time.time() - entry["ts"]) < CACHE_TTL:
            return entry["data"]
        if entry:
            del _cache[url]
    return None

def _cache_set(url: str, data: dict):
    with _cache_lock:
        # LRU eviction
        if len(_cache) >= CACHE_MAX and url not in _cache:
            oldest_key = min(_cache, key=lambda k: _cache[k]["ts"])
            del _cache[oldest_key]
        _cache[url] = {"data": data, "ts": time.time()}


# ── SSRF Protection ─────────────────────────────────────────────────────
BLOCKED_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

def _is_private_ip(hostname: str) -> bool:
    """Resolve hostname and check if the IP is private/reserved."""
    try:
        results = socket.getaddrinfo(hostname, None)
        for family, _type, _proto, _canonname, sockaddr in results:
            ip = ipaddress.ip_address(sockaddr[0])
            for net in BLOCKED_RANGES:
                if ip in net:
                    return True
    except (socket.gaierror, ValueError):
        return True  # Block unresolvable hosts
    return False


# ── OG Extraction ────────────────────────────────────────────────────────
_OG_RE = re.compile(
    r'<meta\s+(?:[^>]*?\s+)?'
    r'(?:property|name)\s*=\s*["\']og:(\w+)["\']'
    r'\s+content\s*=\s*["\']([^"\']*)["\']'
    r'|'
    r'<meta\s+(?:[^>]*?\s+)?'
    r'content\s*=\s*["\']([^"\']*)["\']'
    r'\s+(?:property|name)\s*=\s*["\']og:(\w+)["\']',
    re.IGNORECASE | re.DOTALL,
)

_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)


def _extract_og(html_text: str) -> dict:
    """Extract OpenGraph metadata from raw HTML."""
    og = {}
    for m in _OG_RE.finditer(html_text):
        # Two capture group layouts depending on attribute order
        if m.group(1) and m.group(2):
            og[m.group(1).lower()] = html.unescape(m.group(2).strip())
        elif m.group(3) and m.group(4):
            og[m.group(4).lower()] = html.unescape(m.group(3).strip())

    # Fallback: use <title> if og:title is missing
    if "title" not in og:
        title_match = _TITLE_RE.search(html_text)
        if title_match:
            og["title"] = html.unescape(title_match.group(1).strip())

    return og


def _sanitize(text: str, max_len: int) -> str:
    if not text:
        return ""
    # Strip tags
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


# ── Request Model ────────────────────────────────────────────────────────
class LinkPreviewRequest(BaseModel):
    url: str


# ── Route ────────────────────────────────────────────────────────────────
@router.post("/link-preview")
def fetch_link_preview(
    body: LinkPreviewRequest,
    user: User = Depends(get_current_user),
):
    url = body.url.strip()

    # Validate scheme
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http/https URLs are allowed")

    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid URL")

    # SSRF check
    if _is_private_ip(parsed.hostname):
        raise HTTPException(status_code=400, detail="URL points to a private/reserved network")

    # Check cache
    cached = _cache_get(url)
    if cached is not None:
        return cached

    # Fetch
    try:
        resp = requests.get(
            url,
            timeout=4,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AtlasBot/1.0; +http://localhost)",
                "Accept": "text/html",
            },
            allow_redirects=True,
            stream=True,
        )

        # Validate redirect chain (ensure no redirect to private IP)
        if resp.history:
            for r in resp.history:
                rp = urlparse(r.url)
                if rp.hostname and _is_private_ip(rp.hostname):
                    raise HTTPException(status_code=400, detail="Redirect to private network blocked")
            # Also check final URL
            final_parsed = urlparse(resp.url)
            if final_parsed.hostname and _is_private_ip(final_parsed.hostname):
                raise HTTPException(status_code=400, detail="Redirect to private network blocked")

        # Limit response size (512 KB)
        content_length = resp.headers.get("content-length")
        if content_length and int(content_length) > 512 * 1024:
            raise HTTPException(status_code=400, detail="Response too large")

        # Read up to 512 KB
        raw = resp.content[:512 * 1024]

        # Detect encoding
        encoding = resp.encoding or "utf-8"
        try:
            html_text = raw.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            html_text = raw.decode("utf-8", errors="replace")

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=422, detail="URL fetch timed out")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Link preview fetch failed for {url}: {e}")
        raise HTTPException(status_code=422, detail="Failed to fetch URL")

    # Extract OG
    og = _extract_og(html_text)

    if not og.get("title"):
        raise HTTPException(status_code=422, detail="No metadata found for URL")

    result = {
        "title": _sanitize(og.get("title", ""), 200),
        "description": _sanitize(og.get("description", ""), 300),
        "image": og.get("image", ""),
        "domain": parsed.hostname,
        "url": url,
    }

    # Cache result
    _cache_set(url, result)

    return result
