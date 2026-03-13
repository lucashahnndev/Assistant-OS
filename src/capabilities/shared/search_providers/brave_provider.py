from __future__ import annotations

from typing import Any, Dict, List, Optional

from server.core.secret_manager import resolve_secret_ref

import httpx

from .base import SearchProvider, SearchRequest, SearchResponse, SearchResultItem


class BraveProvider(SearchProvider):
    name = "brave"

    def __init__(
        self,
        *,
        api_base: str = "https://api.search.brave.com/res/v1/web/search",
        api_key: Optional[str] = None,
        timeout_ms: int = 5000,
        retries: int = 1,
        enabled: bool = False,
    ) -> None:
        self.api_base = str(api_base or "https://api.search.brave.com/res/v1/web/search").rstrip("/")
        self.api_key = str(resolve_secret_ref(api_key) or "").strip()
        self.timeout_ms = max(1000, min(int(timeout_ms or 5000), 20000))
        self.retries = max(0, min(int(retries or 1), 3))
        self.enabled = bool(enabled)

    @staticmethod
    def _map_recency(recency_days: int) -> Optional[str]:
        if recency_days <= 0:
            return None
        if recency_days <= 1:
            return "pd"
        if recency_days <= 7:
            return "pw"
        if recency_days <= 31:
            return "pm"
        return "py"

    @staticmethod
    def _normalize_lang(language: str) -> str:
        raw = str(language or "").strip()
        if not raw:
            return "en"
        return raw.split("-", 1)[0].lower()

    def search(self, request: SearchRequest) -> SearchResponse:
        if not self.enabled:
            return SearchResponse(results=[], warnings=["PROVIDER_DISABLED:brave"])
        if not self.api_key:
            return SearchResponse(results=[], warnings=["PROVIDER_MISCONFIGURED:brave:api_key_missing"])

        warnings: List[str] = []
        params: Dict[str, Any] = {
            "q": request.query,
            "count": max(1, min(request.limit, 20)),
            "search_lang": self._normalize_lang(request.language),
        }
        if request.country:
            params["country"] = str(request.country).upper()
        freshness = self._map_recency(request.recency_days)
        if freshness:
            params["freshness"] = freshness

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }

        timeout = httpx.Timeout(self.timeout_ms / 1000.0)
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    resp = client.get(self.api_base, params=params, headers=headers)
                    resp.raise_for_status()
                    payload = resp.json() if resp.content else {}

                web_data = payload.get("web") if isinstance(payload, dict) else {}
                raw_results = web_data.get("results") if isinstance(web_data, dict) else []

                results: List[SearchResultItem] = []
                for row in raw_results if isinstance(raw_results, list) else []:
                    if not isinstance(row, dict):
                        continue
                    url = str(row.get("url") or "").strip()
                    if not url:
                        continue
                    results.append(
                        SearchResultItem(
                            title=str(row.get("title") or "Untitled"),
                            url=url,
                            snippet=str(row.get("description") or ""),
                            source="brave",
                            provider=self.name,
                            published_at=str(row.get("age") or "").strip() or None,
                        )
                    )
                    if len(results) >= request.limit:
                        break
                return SearchResponse(results=results, warnings=warnings)
            except httpx.HTTPStatusError as e:
                status = int(getattr(e.response, "status_code", 0) or 0)
                if status in {401, 403}:
                    warnings.append(f"PROVIDER_AUTH_DENIED:brave:{status}")
                    return SearchResponse(results=[], warnings=warnings)
                last_error = e
                if attempt < self.retries:
                    continue
            except Exception as e:
                last_error = e
                if attempt < self.retries:
                    continue
        warnings.append(f"PROVIDER_FAILED:brave:{last_error}")
        return SearchResponse(results=[], warnings=warnings)
