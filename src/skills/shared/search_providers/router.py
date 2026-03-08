from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence

from .base import SearchProvider, SearchRequest, SearchResultItem
from .brave_provider import BraveProvider
from .commoncrawl_provider import CommonCrawlCdxProvider
from .ddg_provider import DdgProvider
from .openalex_provider import OpenAlexProvider
from .searxng_provider import SearxngProvider
from .utils import apply_domain_filters, cut_results, dedupe_results, merge_warnings, score_result

logger = logging.getLogger("SearchRouter")

_PROVIDER_WEIGHTS = {
    "searxng": 0.85,
    "brave": 0.90,
    "commoncrawl": 0.65,
    "openalex": 0.70,
    "ddg": 0.55,
}


class SearchRouter:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.providers = self._build_providers(self.config)
        self.strict_location_when_query_mentions_city = bool(
            self.config.get("strict_location_when_query_mentions_city", True)
        )

    @staticmethod
    def _provider_config(config: Dict[str, Any], key: str) -> Dict[str, Any]:
        providers_cfg = config.get("providers") if isinstance(config.get("providers"), dict) else {}
        raw = providers_cfg.get(key)
        return raw if isinstance(raw, dict) else {}

    def _build_providers(self, config: Dict[str, Any]) -> List[SearchProvider]:
        timeout_ms = int(config.get("timeout_ms", 5000)) if isinstance(config, dict) else 5000
        retries = int(config.get("retries", 1)) if isinstance(config, dict) else 1

        searx_cfg = self._provider_config(config, "searxng")
        common_cfg = self._provider_config(config, "commoncrawl")
        openalex_cfg = self._provider_config(config, "openalex")
        ddg_cfg = self._provider_config(config, "ddg")
        brave_cfg = self._provider_config(config, "brave")

        providers: List[SearchProvider] = [
            SearxngProvider(
                endpoints=searx_cfg.get("endpoints")
                if isinstance(searx_cfg.get("endpoints"), list)
                else ["https://searx.be", "https://search.inetol.net"],
                engines=searx_cfg.get("engines") if isinstance(searx_cfg.get("engines"), list) else None,
                timeout_ms=int(searx_cfg.get("timeout_ms") or timeout_ms),
                retries=int(searx_cfg.get("retries") or retries),
                enabled=bool(searx_cfg.get("enabled", True)),
            ),
            CommonCrawlCdxProvider(
                collinfo_url=str(common_cfg.get("collinfo_url") or "https://index.commoncrawl.org/collinfo.json"),
                timeout_ms=int(common_cfg.get("timeout_ms") or timeout_ms),
                retries=int(common_cfg.get("retries") or retries),
                max_indexes=int(common_cfg.get("max_indexes") or 2),
                enabled=bool(common_cfg.get("enabled", True)),
            ),
            BraveProvider(
                api_base=str(brave_cfg.get("api_base") or "https://api.search.brave.com/res/v1/web/search"),
                api_key=str(brave_cfg.get("api_key") or ""),
                timeout_ms=int(brave_cfg.get("timeout_ms") or timeout_ms),
                retries=int(brave_cfg.get("retries") or retries),
                enabled=bool(brave_cfg.get("enabled", False)),
            ),
            OpenAlexProvider(
                api_base=str(openalex_cfg.get("api_base") or "https://api.openalex.org"),
                timeout_ms=int(openalex_cfg.get("timeout_ms") or timeout_ms),
                retries=int(openalex_cfg.get("retries") or retries),
                enabled=bool(openalex_cfg.get("enabled", True)),
            ),
            DdgProvider(enabled=bool(ddg_cfg.get("enabled", False))),
        ]

        order = config.get("provider_order") if isinstance(config.get("provider_order"), list) else []
        if not order:
            order = ["searxng", "brave", "ddg", "openalex", "commoncrawl"]

        by_name = {p.name: p for p in providers}
        ordered: List[SearchProvider] = []
        for name in order:
            p = by_name.get(str(name).strip().lower())
            if p is not None:
                ordered.append(p)
        for p in providers:
            if p not in ordered:
                ordered.append(p)
        return ordered

    def search(
        self,
        *,
        query: str,
        limit: int,
        recency_days: int,
        domains_allow: Sequence[str],
        domains_deny: Sequence[str],
        language: str = "en",
        country: str = "",
        location: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        effective_query = self._apply_geo_bias(query, location=location)
        request = SearchRequest(
            query=effective_query,
            limit=limit,
            recency_days=recency_days,
            domains_allow=list(domains_allow),
            domains_deny=list(domains_deny),
            language=str(language or "en"),
            country=str(country or ""),
            location=location if isinstance(location, dict) else None,
        )

        warnings: List[str] = []
        raw_results: List[SearchResultItem] = []
        tried: List[str] = []

        for provider in self.providers:
            tried.append(provider.name)
            try:
                resp = provider.search(request)
                warnings = merge_warnings(warnings, resp.warnings)
                raw_results.extend(resp.results)
                if len(raw_results) >= limit:
                    break
            except Exception as e:
                logger.warning("Search provider failed: %s (%s)", provider.name, e)
                warnings.append(f"PROVIDER_FAILED:{provider.name}")

        filtered = apply_domain_filters(raw_results, domains_allow=domains_allow, domains_deny=domains_deny)
        deduped = dedupe_results(filtered)
        location_city = str((location or {}).get("city") or "").strip()
        location_country = str((location or {}).get("country") or "").strip()
        query_mentions_city = self._contains_location_token(query, location_city)

        for item in deduped:
            provider_weight = _PROVIDER_WEIGHTS.get(item.provider, 0.5)
            item.confidence_score = score_result(
                item,
                query=query,
                provider_weight=provider_weight,
                recency_days=recency_days,
            )
            if self._item_matches_location(item, city=location_city, country=location_country):
                item.confidence_score = min(1.0, item.confidence_score + 0.18)

        deduped.sort(key=lambda x: (x.confidence_score, -x.rank), reverse=True)
        if query_mentions_city and location_city:
            city_matched = [
                item for item in deduped if self._item_matches_location(item, city=location_city, country=location_country)
            ]
            if self.strict_location_when_query_mentions_city:
                if city_matched:
                    deduped = city_matched
                else:
                    warnings = merge_warnings(
                        warnings,
                        [f"LOCATION_STRICT_NO_MATCH:city={location_city}"],
                    )
                    deduped = []
            elif city_matched:
                deduped = city_matched + [item for item in deduped if item not in city_matched]

        ranked = cut_results(deduped, limit=limit)

        provider_name = "search_router"
        if ranked:
            provider_name = ranked[0].provider

        payload_results = [r.to_payload() for r in ranked]
        return {
            "provider": provider_name,
            "results": payload_results,
            "warnings": warnings,
            "providers_tried": tried,
        }

    @staticmethod
    def _normalize_text(value: str) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        norm = unicodedata.normalize("NFKD", raw)
        ascii_only = "".join(ch for ch in norm if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", ascii_only).strip()

    @classmethod
    def _contains_location_token(cls, text: str, token: str) -> bool:
        lhs = cls._normalize_text(text)
        rhs = cls._normalize_text(token)
        if not lhs or not rhs:
            return False
        return rhs in lhs

    @classmethod
    def _item_matches_location(cls, item: SearchResultItem, *, city: str, country: str) -> bool:
        haystack = cls._normalize_text(f"{item.title} {item.snippet} {item.url}")
        city_norm = cls._normalize_text(city)
        country_norm = cls._normalize_text(country)
        city_ok = bool(city_norm and city_norm in haystack)
        country_ok = bool(country_norm and country_norm in haystack)
        return city_ok or country_ok

    @staticmethod
    def _is_location_sensitive_query(query: str) -> bool:
        q = SearchRouter._normalize_text(query)
        if not q:
            return False
        markers = (
            "near me",
            "nearby",
            "in ",
            "at ",
            "em ",
            "na ",
            "no ",
            "onde",
            "where",
            "restaurante",
            "restaurant",
            "cafeteria",
            "cafe",
            "hotel",
            "farmacia",
            "pharmacy",
            "hospital",
            "loja",
            "store",
            "mercado",
            "market",
        )
        return any(marker in q for marker in markers)

    @staticmethod
    def _apply_geo_bias(query: str, *, location: Optional[Dict[str, Any]]) -> str:
        base = str(query or "").strip()
        if not base:
            return base
        if not SearchRouter._is_location_sensitive_query(base):
            return base
        if not isinstance(location, dict):
            return base
        city = str(location.get("city") or "").strip()
        country = str(location.get("country") or "").strip()
        parts = [p for p in (city, country) if p]
        if not parts:
            return base
        lowered = base.lower()
        missing = [p for p in parts if p.lower() not in lowered]
        if not missing:
            return base
        return f"{base} {' '.join(missing)}".strip()
