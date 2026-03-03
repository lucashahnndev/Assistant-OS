from __future__ import annotations

from typing import List

from .base import SearchProvider, SearchRequest, SearchResponse, SearchResultItem

try:
    from ddgs import DDGS  # type: ignore
except Exception:  # pragma: no cover
    from duckduckgo_search import DDGS  # type: ignore


class DdgProvider(SearchProvider):
    name = "ddg"

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = bool(enabled)

    @staticmethod
    def _map_recency(recency_days: int) -> str | None:
        if recency_days <= 0:
            return None
        if recency_days <= 1:
            return "d"
        if recency_days <= 7:
            return "w"
        if recency_days <= 31:
            return "m"
        return "y"

    @staticmethod
    def _map_region(country: str, language: str) -> str | None:
        cc = str(country or "").strip().lower()
        lang = str(language or "").strip().split("-", 1)[0].lower()
        if cc == "br":
            return "br-pt"
        if cc == "us":
            return "us-en"
        if cc and lang:
            return f"{cc}-{lang}"
        return None

    def search(self, request: SearchRequest) -> SearchResponse:
        if not self.enabled:
            return SearchResponse(results=[], warnings=["PROVIDER_DISABLED:ddg"])

        warnings: List[str] = []
        try:
            with DDGS() as ddgs:
                generator = None
                region = self._map_region(request.country, request.language)
                if request.recency_days > 0:
                    try:
                        generator = ddgs.text(
                            request.query,
                            max_results=request.limit,
                            timelimit=self._map_recency(request.recency_days),
                            region=region,
                        )
                    except TypeError:
                        warnings.append("RECENCY_UNSUPPORTED")
                if generator is None:
                    try:
                        generator = ddgs.text(request.query, max_results=request.limit, region=region)
                    except TypeError:
                        generator = ddgs.text(request.query, max_results=request.limit)

                results: List[SearchResultItem] = []
                for row in generator:
                    if not isinstance(row, dict):
                        continue
                    url = str(row.get("href") or row.get("url") or "").strip()
                    if not url:
                        continue
                    results.append(
                        SearchResultItem(
                            title=str(row.get("title") or row.get("heading") or "Untitled"),
                            url=url,
                            snippet=str(row.get("body") or row.get("snippet") or row.get("text") or ""),
                            source="duckduckgo",
                            provider=self.name,
                        )
                    )
                    if len(results) >= request.limit:
                        break
                return SearchResponse(results=results, warnings=warnings)
        except Exception as e:
            msg = str(e).lower()
            if "401" in msg or "unauthorized" in msg:
                warnings.append("PROVIDER_AUTH_DENIED:ddg:401")
            elif "403" in msg or "forbidden" in msg:
                warnings.append("PROVIDER_AUTH_DENIED:ddg:403")
            else:
                warnings.append(f"PROVIDER_FAILED:ddg:{e}")
            return SearchResponse(results=[], warnings=warnings)
