from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .base import SearchProvider, SearchRequest, SearchResponse, SearchResultItem

logger = logging.getLogger("SearxngProvider")


class SearxngProvider(SearchProvider):
    name = "searxng"

    def __init__(
        self,
        *,
        endpoints: Optional[List[str]] = None,
        engines: Optional[List[str]] = None,
        timeout_ms: int = 5000,
        retries: int = 1,
        enabled: bool = True,
    ) -> None:
        self.endpoints = [str(e).rstrip("/") for e in (endpoints or []) if str(e).strip()]
        self.engines = [str(e).strip() for e in (engines or []) if str(e).strip()]
        self.timeout_ms = max(1000, min(int(timeout_ms or 5000), 20000))
        self.retries = max(0, min(int(retries or 1), 3))
        self.enabled = bool(enabled)

    @staticmethod
    def _map_recency(recency_days: int) -> Optional[str]:
        if recency_days <= 0:
            return None
        if recency_days <= 1:
            return "day"
        if recency_days <= 7:
            return "week"
        if recency_days <= 31:
            return "month"
        return "year"

    def _request_once(self, endpoint: str, request: SearchRequest) -> Dict[str, Any]:
        language = str(request.language or "all").strip() or "all"
        params: Dict[str, Any] = {
            "q": request.query,
            "format": "json",
            "language": language,
            "safesearch": 0,
        }
        if self.engines:
            params["engines"] = ",".join(self.engines)
        rec = self._map_recency(request.recency_days)
        if rec:
            params["time_range"] = rec

        timeout = httpx.Timeout(self.timeout_ms / 1000.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(f"{endpoint}/search", params=params)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    def search(self, request: SearchRequest) -> SearchResponse:
        if not self.enabled:
            return SearchResponse(results=[], warnings=["PROVIDER_DISABLED:searxng"])

        if not self.endpoints:
            return SearchResponse(results=[], warnings=["PROVIDER_MISCONFIGURED:searxng:endpoints_missing"])

        warnings: List[str] = []
        for endpoint in self.endpoints:
            last_error = None
            for attempt in range(self.retries + 1):
                try:
                    payload = self._request_once(endpoint, request)
                    raw_results = payload.get("results") if isinstance(payload, dict) else []
                    results: List[SearchResultItem] = []
                    for raw in raw_results if isinstance(raw_results, list) else []:
                        if not isinstance(raw, dict):
                            continue
                        url = str(raw.get("url") or "").strip()
                        if not url:
                            continue
                        title = str(raw.get("title") or "Untitled")
                        snippet = str(raw.get("content") or raw.get("snippet") or "")
                        published_at = str(raw.get("publishedDate") or raw.get("published_date") or "").strip() or None
                        results.append(
                            SearchResultItem(
                                title=title,
                                url=url,
                                snippet=snippet,
                                source="searxng",
                                provider=self.name,
                                published_at=published_at,
                            )
                        )
                        if len(results) >= request.limit:
                            break
                    return SearchResponse(results=results, warnings=warnings)
                except httpx.HTTPStatusError as e:
                    status = int(getattr(e.response, "status_code", 0) or 0)
                    if status in {401, 403}:
                        warnings.append(f"PROVIDER_AUTH_DENIED:searxng:{endpoint}:{status}")
                        break
                    last_error = e
                    if attempt < self.retries:
                        continue
                except Exception as e:
                    last_error = e
                    if attempt < self.retries:
                        continue
            logger.warning("SearXNG endpoint failed: %s (%s)", endpoint, last_error)
            warnings.append(f"PROVIDER_FAILED:searxng:{endpoint}")

        return SearchResponse(results=[], warnings=warnings)
