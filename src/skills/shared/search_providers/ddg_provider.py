from __future__ import annotations

import re
import unicodedata
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

    @staticmethod
    def _is_recency_sensitive_query(query: str) -> bool:
        text = str(query or "").strip().lower()
        if not text:
            return False
        markers = (
            "latest",
            "today",
            "breaking",
            "news",
            "earnings",
            "stock",
            "price",
            "update",
            "agora",
            "hoje",
            "notícia",
            "noticia",
            "últimas",
            "ultimas",
        )
        if any(marker in text for marker in markers):
            return True
        if re.search(r"\b20\d{2}\b", text):
            return True
        return False

    @staticmethod
    def _has_cjk(text: str) -> bool:
        if not text:
            return False
        return bool(re.search(r"[\u3400-\u4DBF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]", text))

    @classmethod
    def _is_language_mismatch(cls, *, title: str, snippet: str, query: str, language: str) -> bool:
        lang = str(language or "").strip().lower()
        if not lang:
            return False
        if cls._has_cjk(query):
            return False
        if not (lang.startswith("en") or lang.startswith("pt") or lang.startswith("es")):
            return False
        hay = f"{title} {snippet}"
        return cls._has_cjk(hay)

    @staticmethod
    def _normalize_text(value: str) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        norm = unicodedata.normalize("NFKD", raw)
        ascii_only = "".join(ch for ch in norm if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", ascii_only).strip()

    @classmethod
    def _query_variants(cls, request: SearchRequest) -> List[str]:
        base = str(request.query or "").strip()
        if not base:
            return []
        out: List[str] = [base]
        loc = request.location if isinstance(request.location, dict) else {}
        city = str(loc.get("city") or "").strip()
        country = str(loc.get("country") or "").strip()
        if city and cls._normalize_text(city) not in cls._normalize_text(base):
            out.append(f"{base} {city}")
            out.append(f"{base} \"{city}\"")
        if country and cls._normalize_text(country) not in cls._normalize_text(base):
            out.append(f"{base} {country}")
        dedup: List[str] = []
        seen = set()
        for q in out:
            key = cls._normalize_text(q)
            if key and key not in seen:
                seen.add(key)
                dedup.append(q)
        return dedup

    def search(self, request: SearchRequest) -> SearchResponse:
        if not self.enabled:
            return SearchResponse(results=[], warnings=["PROVIDER_DISABLED:ddg"])

        warnings: List[str] = []
        try:
            with DDGS() as ddgs:
                results: List[SearchResultItem] = []
                raw_candidates: List[SearchResultItem] = []
                region = self._map_region(request.country, request.language)
                for q in self._query_variants(request):
                    generator = None
                    if request.recency_days > 0 and self._is_recency_sensitive_query(q):
                        try:
                            generator = ddgs.text(
                                q,
                                max_results=request.limit,
                                timelimit=self._map_recency(request.recency_days),
                                region=region,
                            )
                        except TypeError:
                            warnings.append("RECENCY_UNSUPPORTED")
                    if generator is None:
                        try:
                            generator = ddgs.text(q, max_results=request.limit, region=region)
                        except TypeError:
                            generator = ddgs.text(q, max_results=request.limit)

                    for row in generator:
                        if not isinstance(row, dict):
                            continue
                        url = str(row.get("href") or row.get("url") or "").strip()
                        if not url:
                            continue
                        title = str(row.get("title") or row.get("heading") or "Untitled")
                        snippet = str(row.get("body") or row.get("snippet") or row.get("text") or "")
                        candidate = SearchResultItem(
                            title=title,
                            url=url,
                            snippet=snippet,
                            source="duckduckgo",
                            provider=self.name,
                        )
                        raw_candidates.append(candidate)
                        if self._is_language_mismatch(
                            title=title,
                            snippet=snippet,
                            query=q,
                            language=request.language,
                        ):
                            continue
                        results.append(candidate)
                        if len(results) >= request.limit:
                            break
                    if len(results) >= request.limit:
                        break
                if not results and raw_candidates:
                    warnings.append("LANGUAGE_FILTER_RELAXED:ddg")
                    return SearchResponse(results=raw_candidates[: request.limit], warnings=warnings)

                if not results:
                    # Fallback retry without region/timelimit.
                    for q in self._query_variants(request):
                        try:
                            generator = ddgs.text(q, max_results=request.limit)
                        except TypeError:
                            generator = ddgs.text(q, max_results=request.limit)
                        for row in generator:
                            if not isinstance(row, dict):
                                continue
                            url = str(row.get("href") or row.get("url") or "").strip()
                            if not url:
                                continue
                            title = str(row.get("title") or row.get("heading") or "Untitled")
                            snippet = str(row.get("body") or row.get("snippet") or row.get("text") or "")
                            results.append(
                                SearchResultItem(
                                    title=title,
                                    url=url,
                                    snippet=snippet,
                                    source="duckduckgo",
                                    provider=self.name,
                                )
                            )
                            if len(results) >= request.limit:
                                break
                        if len(results) >= request.limit:
                            break
                    if results:
                        warnings.append("FALLBACK_RETRY_NO_REGION:ddg")
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
