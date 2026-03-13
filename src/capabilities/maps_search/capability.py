import logging
from typing import Any, Dict, List, Optional
from server.core.secret_manager import resolve_secret_ref

import requests
from urllib.parse import quote_plus

from ..base import CapabilityBase
from services.location.location_service import LocationService

logger = logging.getLogger("MapsSearchCapability")


class MapsSearchCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "maps"
        self.location_service = LocationService()

    @property
    def name(self) -> str:
        return "maps_search"

    @property
    def actions(self) -> List[str]:
        return ["search"]

    @staticmethod
    def _result(ok: bool, status: str, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": ok, "status": status}
        payload.update(extra)
        return payload

    @staticmethod
    def _to_int(value: Any, default: int, min_value: int, max_value: int) -> int:
        try:
            out = int(value)
        except Exception:
            out = default
        return max(min_value, min(max_value, out))

    @staticmethod
    def _to_float(value: Any, default: float, min_value: float, max_value: float) -> float:
        try:
            out = float(value)
        except Exception:
            out = default
        return max(min_value, min(max_value, out))

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "sim", "on"}
        return False

    @staticmethod
    def _parse_latlon(value: Any) -> Optional[str]:
        if value is None:
            return None
        raw = str(value).strip()
        if "," not in raw:
            return None
        parts = [p.strip() for p in raw.split(",", 1)]
        if len(parts) != 2:
            return None
        try:
            lat = float(parts[0])
            lon = float(parts[1])
        except Exception:
            return None
        return f"{lat},{lon}"

    @staticmethod
    def _normalize_place(item: Dict[str, Any], rank: int) -> Dict[str, Any]:
        place_id = item.get("place_id")
        maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else None
        return {
            "rank": rank,
            "name": item.get("name"),
            "address": item.get("formatted_address"),
            "placeId": place_id,
            "url": maps_url,
            "location": (item.get("geometry") or {}).get("location"),
            "rating": item.get("rating"),
            "user_ratings_total": item.get("user_ratings_total"),
            "types": item.get("types") or [],
            "open_now": ((item.get("opening_hours") or {}).get("open_now")),
            "confidenceScore": 0.9,
        }

    def _get_api_key(self) -> Optional[str]:
        api_key = resolve_secret_ref(self.config.get("apiKey"))
        return str(api_key or "").strip() or None

    @staticmethod
    def _sanitize_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _resolve_query(params: Dict[str, Any]) -> str:
        for key in ("query", "search_query", "searchQuery", "q", "term", "text"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _resolve_city(params: Dict[str, Any]) -> str:
        for key in ("city", "location", "place", "where"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _compose_query(self, query: str, category: str, city: str, keywords: str) -> str:
        query = self._sanitize_text(query)
        category = self._sanitize_text(category)
        city = self._sanitize_text(city)
        keywords = self._sanitize_text(keywords)

        if query:
            composed = query
            if city and city.lower() not in composed.lower():
                composed = f"{composed} em {city}"
            if keywords:
                composed = f"{composed} {keywords}"
            return composed.strip()

        head = category or keywords or "lugares"
        if city:
            return f"{head} em {city}".strip()
        return head.strip()

    def _build_variants(self, base_query: str, category: str, city: str, max_variants: int) -> List[str]:
        variants: List[str] = [base_query]
        category = self._sanitize_text(category)
        city = self._sanitize_text(city)

        if category and city:
            variants.extend(
                [
                    f"melhores {category} em {city}",
                    f"{category} bem avaliados em {city}",
                    f"{category} abertos agora em {city}",
                ]
            )
        elif city:
            variants.extend(
                [
                    f"pontos de interesse em {city}",
                    f"lugares para visitar em {city}",
                ]
            )
        elif category:
            variants.extend(
                [
                    f"melhores {category}",
                    f"{category} mais bem avaliados",
                ]
            )

        dedup: List[str] = []
        seen = set()
        for item in variants:
            key = item.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            dedup.append(item.strip())
            if len(dedup) >= max_variants:
                break
        return dedup

    def _extract_coords_from_context(self, context: Dict[str, Any]) -> Optional[str]:
        session = context.get("session") if isinstance(context, dict) else None
        context_data = getattr(session, "context", {}) if session else {}
        current_loc = self.location_service.get_current_location(context_data)
        if not current_loc:
            return None
        lat = current_loc.get("latitude")
        lon = current_loc.get("longitude")
        if lat is None or lon is None:
            return None
        return f"{lat},{lon}"

    def _geocode_text(self, auth: Dict[str, Any], text: str) -> Optional[str]:
        query = self._sanitize_text(text)
        if not query:
            return None
        try:
            req_params: Dict[str, Any] = {"address": query}
            req_params.update(auth.get("params") or {})
            response = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params=req_params,
                headers=auth.get("headers") or {},
                timeout=10,
            )
            data = response.json()
            if response.status_code != 200 or data.get("status") != "OK":
                return None
            first = (data.get("results") or [{}])[0]
            loc = (first.get("geometry") or {}).get("location") or {}
            lat = loc.get("lat")
            lon = loc.get("lng")
            if lat is None or lon is None:
                return None
            return f"{lat},{lon}"
        except Exception as exc:
            logger.warning(f"Maps geocode fallback failed: {exc}")
            return None

    def _search_google_places(
        self,
        auth: Dict[str, Any],
        query: str,
        location_bias: Optional[str],
        radius: int,
        place_type: Optional[str],
        open_now: bool,
    ) -> Dict[str, Any]:
        request_params: Dict[str, Any] = {
            "query": query,
            "language": self.config.get("defaults", {}).get("language", "pt-BR"),
            "region": self.config.get("defaults", {}).get("region", "BR"),
        }
        request_params.update(auth.get("params") or {})
        if location_bias:
            request_params["location"] = location_bias
            request_params["radius"] = radius
        if place_type:
            request_params["type"] = place_type
        if open_now:
            request_params["opennow"] = "true"

        response = requests.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params=request_params,
            headers=auth.get("headers") or {},
            timeout=10,
        )
        data = response.json()
        status = data.get("status")
        if response.status_code != 200 or (status not in {"OK", "ZERO_RESULTS"}):
            return {
                "ok": False,
                "error_code": "GOOGLE_MAPS_API_ERROR",
                "error_details": data.get("error_message") or status or f"HTTP {response.status_code}",
            }

        places = [self._normalize_place(item, rank=i + 1) for i, item in enumerate(data.get("results") or [])]
        return {
            "ok": True,
            "status": "empty" if status == "ZERO_RESULTS" else "success",
            "places": places,
        }

    @staticmethod
    def _is_google_maps_denied(message: str) -> bool:
        text = str(message or "").lower()
        markers = [
            "request_denied",
            "enable billing",
            "billing",
            "api is not activated",
            "not authorized",
            "api key",
            "forbidden",
        ]
        return any(marker in text for marker in markers)

    def _fallback_to_web_discover(
        self,
        context: Dict[str, Any],
        query: str,
        city: str,
        limit: int,
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        registry = context.get("capability_registry") if isinstance(context, dict) else None
        dispatch = getattr(registry, "dispatch", None) if registry else None
        if not callable(dispatch):
            return None

        composed_query = query.strip()
        if city and city.strip() and city.lower() not in composed_query.lower():
            composed_query = f"{composed_query} {city.strip()}".strip()

        search_params = {
            "query": composed_query,
            "mode": "links",
            "limit": min(max(3, limit), 8),
        }
        try:
            web_result = dispatch("web.search.discover", search_params, context)
        except Exception as exc:
            logger.warning(f"Maps fallback dispatch failed: {exc}")
            return None

        if not isinstance(web_result, dict) or not web_result.get("ok"):
            return None

        links = web_result.get("results") if isinstance(web_result.get("results"), list) else []
        if not links:
            return None

        places: List[Dict[str, Any]] = []
        for i, item in enumerate(links[:limit], start=1):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or item.get("name") or f"Result {i}").strip()
            snippet = str(item.get("snippet") or item.get("description") or "").strip()
            maps_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(title)}"
            if city and city.strip():
                maps_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(f'{title} {city.strip()}')}"
            places.append(
                {
                    "rank": i,
                    "name": title,
                    "address": snippet or None,
                    "placeId": None,
                    "url": maps_url,
                    "location": None,
                    "rating": None,
                    "user_ratings_total": None,
                    "types": [],
                    "open_now": None,
                    "confidenceScore": 0.45,
                    "source_url": url,
                }
            )

        if not places:
            return None

        return self._result(
            ok=True,
            status="fallback",
            provider="web_search_fallback",
            query=composed_query,
            city=city or None,
            count=len(places),
            places=places,
            best=places[0],
            queries_executed=[composed_query],
            fallback_from="google_maps",
            fallback_reason=reason,
            warning="Google Maps API indisponível; usando fallback de busca web.",
        )

    def _resolve_location_bias(
        self,
        auth: Dict[str, Any],
        near: str,
        city: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        near = self._sanitize_text(near)
        city = self._sanitize_text(city)

        direct = self._parse_latlon(near)
        if direct:
            return direct
        if near:
            geocoded = self._geocode_text(auth, near)
            if geocoded:
                return geocoded

        if city:
            geocoded = self._geocode_text(auth, city)
            if geocoded:
                return geocoded

        return self._extract_coords_from_context(context)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        if action != "search":
            return self._result(
                ok=False,
                status="error",
                error_code="UNKNOWN_ACTION",
                message=f"Unknown action para maps_search: {action_id}",
            )

        query = self._sanitize_text(self._resolve_query(params))
        city = self._sanitize_text(self._resolve_city(params))
        category = self._sanitize_text(params.get("category") or params.get("place_type"))
        keywords_raw = params.get("keywords")
        if isinstance(keywords_raw, list):
            keywords = " ".join(str(x).strip() for x in keywords_raw if str(x).strip())
        else:
            keywords = self._sanitize_text(keywords_raw)

        base_query = self._compose_query(query, category, city, keywords)
        if not base_query:
            return self._result(
                ok=False,
                status="error",
                error_code="MISSING_QUERY",
                message="query/category/city are required",
            )

        near = self._sanitize_text(params.get("near"))
        radius = self._to_int(params.get("radius"), default=5000, min_value=500, max_value=50000)
        place_type = self._sanitize_text(params.get("type"))
        limit = self._to_int(params.get("limit") or params.get("max_results") or params.get("maxResults"), default=8, min_value=1, max_value=20)
        min_rating = self._to_float(params.get("min_rating"), default=0.0, min_value=0.0, max_value=5.0)
        sort_by = self._sanitize_text(params.get("sort_by")).lower() or "relevance"

        mode = self._sanitize_text(params.get("mode")).lower() or "standard"
        diversify = self._to_bool(params.get("diversify"))
        if diversify and mode == "standard":
            mode = "diverse"
        if mode not in {"standard", "diverse"}:
            mode = "standard"
        open_now = self._to_bool(params.get("open_now"))

        api_key = self._get_api_key()
        if not api_key:
            fallback = self._fallback_to_web_discover(
                context=context,
                query=base_query,
                city=city,
                limit=limit,
                reason="MISSING_GOOGLE_MAPS_API_KEY",
            )
            if fallback:
                return fallback
            return self._result(
                ok=False,
                status="error",
                error_code="MISSING_GOOGLE_MAPS_API_KEY",
                message="Google Maps API key secret is not configured.",
                missing_fields=["apiKey"],
            )
        auth = {
            "mode": "api_key",
            "headers": {},
            "params": {"key": api_key},
            "token_payload": None,
            "reason": None,
        }

        location_bias = self._resolve_location_bias(auth, near, city, context)
        max_variants = self._to_int(params.get("max_variants"), default=3, min_value=1, max_value=5)
        query_variants = [base_query] if mode == "standard" else self._build_variants(base_query, category, city, max_variants)

        try:
            merged: List[Dict[str, Any]] = []
            seen_place_ids = set()
            for variant in query_variants:
                result = self._search_google_places(
                    auth=auth,
                    query=variant,
                    location_bias=location_bias,
                    radius=radius,
                    place_type=place_type or None,
                    open_now=open_now,
                )
                if not result.get("ok"):
                    provider_message = str(result.get("message") or "")
                    provider_error = result.get("error", "GOOGLE_MAPS_API_ERROR")
                    can_fallback_to_web = provider_error == "GOOGLE_MAPS_API_ERROR" and (
                        self._is_google_maps_denied(provider_message)
                    )
                    if can_fallback_to_web:
                        fallback = self._fallback_to_web_discover(
                            context=context,
                            query=base_query,
                            city=city,
                            limit=limit,
                            reason=provider_message or provider_error,
                        )
                        if fallback:
                            return fallback
                    return self._result(
                        ok=False,
                        status="error",
                        error_code=provider_error,
                        message=provider_message,
                        provider="google_maps",
                        fallback_action="web.search.discover" if can_fallback_to_web else None,
                        fallback_params=(
                            {
                                "query": base_query,
                                "mode": "links",
                                "limit": min(limit, 5),
                            }
                            if can_fallback_to_web
                            else None
                        ),
                    )
                for item in result.get("places", []):
                    pid = item.get("placeId") or f"{item.get('name')}::{item.get('address')}"
                    if pid in seen_place_ids:
                        continue
                    seen_place_ids.add(pid)
                    merged.append(item)

            if min_rating > 0:
                merged = [p for p in merged if (p.get("rating") or 0) >= min_rating]

            if sort_by == "rating":
                merged.sort(key=lambda x: (x.get("rating") or 0, x.get("user_ratings_total") or 0), reverse=True)

            merged = merged[:limit]
            for idx, item in enumerate(merged, start=1):
                item["rank"] = idx

            status = "success" if merged else "empty"
            return self._result(
                ok=True,
                status=status,
                provider="google_maps_oauth" if auth.get("mode") == "oauth" else "google_maps",
                query=base_query,
                mode=mode,
                city=city or None,
                location_bias=location_bias,
                count=len(merged),
                places=merged,
                best=merged[0] if merged else None,
                queries_executed=query_variants,
                filters={
                    "radius": radius,
                    "type": place_type or None,
                    "open_now": open_now,
                    "min_rating": min_rating,
                    "sort_by": sort_by,
                    "limit": limit,
                },
            )
        except Exception as e:
            logger.error(f"Maps Search Execution Error: {e}")
            return self._result(
                ok=False,
                status="error",
                error_code="MAPS_SEARCH_EXCEPTION",
                message=str(e),
                provider="google_maps",
            )
