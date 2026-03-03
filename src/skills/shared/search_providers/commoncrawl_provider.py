from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from datetime import timezone
from typing import Any, Dict, List, Optional

import httpx

from .base import SearchProvider, SearchRequest, SearchResponse, SearchResultItem
from .utils import recency_threshold

logger = logging.getLogger("CommonCrawlProvider")


class CommonCrawlCdxProvider(SearchProvider):
    name = "commoncrawl"

    def __init__(
        self,
        *,
        collinfo_url: str = "https://index.commoncrawl.org/collinfo.json",
        timeout_ms: int = 6000,
        retries: int = 1,
        max_indexes: int = 2,
        enabled: bool = True,
    ) -> None:
        self.collinfo_url = str(collinfo_url or "").strip()
        self.timeout_ms = max(1000, min(int(timeout_ms or 6000), 25000))
        self.retries = max(0, min(int(retries or 1), 3))
        self.max_indexes = max(1, min(int(max_indexes or 2), 10))
        self.enabled = bool(enabled)

    @staticmethod
    def _query_pattern(query: str) -> str:
        tokens = re.findall(r"[a-z0-9]{3,}", str(query or "").lower())
        if not tokens:
            return "*"
        primary = "*".join(tokens[:3])
        return f"*{primary}*"

    def _load_indexes(self, client: httpx.Client) -> List[str]:
        if not self.collinfo_url:
            return []
        resp = client.get(self.collinfo_url)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list):
            return []
        urls: List[str] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            api_url = str(item.get("cdx-api") or "").strip()
            if api_url:
                urls.append(api_url)
            if len(urls) >= self.max_indexes:
                break
        return urls

    def _search_index(self, client: httpx.Client, index_url: str, request: SearchRequest) -> List[SearchResultItem]:
        params = {
            "url": self._query_pattern(request.query),
            "output": "json",
            "fl": "url,timestamp,status,mime",
            "filter": ["status:200", "mime:text/html"],
            "limit": str(max(10, request.limit * 4)),
        }
        resp = client.get(index_url, params=params)
        resp.raise_for_status()

        results: List[SearchResultItem] = []
        threshold = recency_threshold(request.recency_days)
        for line in (resp.text or "").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            url = str(data.get("url") or "").strip()
            if not url:
                continue
            ts = str(data.get("timestamp") or "").strip()
            published_at = None
            if len(ts) >= 8 and ts.isdigit():
                year = ts[:4]
                month = ts[4:6]
                day = ts[6:8]
                published_at = f"{year}-{month}-{day}"
                if threshold is not None:
                    try:
                        parsed = datetime.fromisoformat(published_at + "T00:00:00+00:00")
                    except Exception:
                        parsed = None
                    if parsed is not None and parsed.replace(tzinfo=timezone.utc) < threshold:
                        continue
            results.append(
                SearchResultItem(
                    title=url,
                    url=url,
                    snippet="URL candidate from Common Crawl index.",
                    source="commoncrawl",
                    provider=self.name,
                    published_at=published_at,
                    status_code=200,
                )
            )
            if len(results) >= request.limit:
                break
        return results

    def search(self, request: SearchRequest) -> SearchResponse:
        if not self.enabled:
            return SearchResponse(results=[], warnings=["PROVIDER_DISABLED:commoncrawl"])

        timeout = httpx.Timeout(self.timeout_ms / 1000.0)
        warnings: List[str] = []
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    indexes = self._load_indexes(client)
                    if not indexes:
                        return SearchResponse(results=[], warnings=["PROVIDER_EMPTY:commoncrawl:indexes_not_found"])

                    results: List[SearchResultItem] = []
                    for index_url in indexes:
                        try:
                            results.extend(self._search_index(client, index_url, request))
                        except Exception as e:
                            logger.warning("CommonCrawl index failed: %s (%s)", index_url, e)
                            warnings.append(f"PROVIDER_FAILED:commoncrawl:{index_url}")
                        if len(results) >= request.limit:
                            break
                    return SearchResponse(results=results[: request.limit], warnings=warnings)
            except httpx.HTTPStatusError as e:
                status = int(getattr(e.response, "status_code", 0) or 0)
                if status in {401, 403}:
                    warnings.append(f"PROVIDER_AUTH_DENIED:commoncrawl:{status}")
                    return SearchResponse(results=[], warnings=warnings)
                last_error = e
                if attempt < self.retries:
                    continue
            except Exception as e:
                last_error = e
                if attempt < self.retries:
                    continue
        warnings.append(f"PROVIDER_FAILED:commoncrawl:{last_error}")
        return SearchResponse(results=[], warnings=warnings)
