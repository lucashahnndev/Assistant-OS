from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx

from .base import SearchProvider, SearchRequest, SearchResponse, SearchResultItem


class OpenAlexProvider(SearchProvider):
    name = "openalex"

    def __init__(
        self,
        *,
        api_base: str = "https://api.openalex.org",
        timeout_ms: int = 5000,
        retries: int = 1,
        enabled: bool = True,
    ) -> None:
        self.api_base = str(api_base or "https://api.openalex.org").rstrip("/")
        self.timeout_ms = max(1000, min(int(timeout_ms or 5000), 20000))
        self.retries = max(0, min(int(retries or 1), 3))
        self.enabled = bool(enabled)

    def _build_params(self, request: SearchRequest) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "search": request.query,
            "per-page": max(1, min(request.limit, 50)),
            "sort": "relevance_score:desc",
        }
        if request.recency_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=request.recency_days)
            params["filter"] = f"from_publication_date:{cutoff.strftime('%Y-%m-%d')}"
        return params

    def search(self, request: SearchRequest) -> SearchResponse:
        if not self.enabled:
            return SearchResponse(results=[], warnings=["PROVIDER_DISABLED:openalex"])

        timeout = httpx.Timeout(self.timeout_ms / 1000.0)
        params = self._build_params(request)
        warnings: List[str] = []

        last_error = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    resp = client.get(f"{self.api_base}/works", params=params)
                    resp.raise_for_status()
                    payload = resp.json()
                raw_results = payload.get("results") if isinstance(payload, dict) else []
                results: List[SearchResultItem] = []
                for row in raw_results if isinstance(raw_results, list) else []:
                    if not isinstance(row, dict):
                        continue
                    title = str(row.get("display_name") or "Untitled")
                    abstract = str(row.get("abstract") or "")
                    primary = row.get("primary_location") if isinstance(row.get("primary_location"), dict) else {}
                    landing = str(primary.get("landing_page_url") or "").strip()
                    if not landing:
                        ids = row.get("ids") if isinstance(row.get("ids"), dict) else {}
                        landing = str(ids.get("openalex") or "").strip()
                    if not landing:
                        continue
                    pub_date = str(row.get("publication_date") or "").strip() or None
                    results.append(
                        SearchResultItem(
                            title=title,
                            url=landing,
                            snippet=abstract,
                            source="openalex",
                            provider=self.name,
                            published_at=pub_date,
                        )
                    )
                    if len(results) >= request.limit:
                        break
                return SearchResponse(results=results, warnings=warnings)
            except httpx.HTTPStatusError as e:
                status = int(getattr(e.response, "status_code", 0) or 0)
                if status in {401, 403}:
                    warnings.append(f"PROVIDER_AUTH_DENIED:openalex:{status}")
                    return SearchResponse(results=[], warnings=warnings)
                last_error = e
                if attempt < self.retries:
                    continue
            except Exception as e:
                last_error = e
                if attempt < self.retries:
                    continue
        warnings.append(f"PROVIDER_FAILED:openalex:{last_error}")
        return SearchResponse(results=[], warnings=warnings)
