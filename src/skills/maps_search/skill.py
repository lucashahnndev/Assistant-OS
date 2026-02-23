import logging
import os
from typing import Any, Dict, List, Optional

import requests

from ..base import SkillBase
from services.location.location_service import LocationService

logger = logging.getLogger("MapsSearchSkill")


class MapsSearchSkill(SkillBase):
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
    def _result(ok: bool, status: str, text: str, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": ok, "status": status, "text": text}
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

    @staticmethod
    def _summary(query: str, city: str, places: List[Dict[str, Any]], mode: str) -> str:
        suffix = f" em {city}" if city else ""
        if not places:
            return f"Nenhum resultado encontrado para '{query}'{suffix}."
        lines = [f"Encontrei {len(places)} resultado(s) para '{query}'{suffix} (modo: {mode})."]
        for p in places[:5]:
            title = p.get("name") or "Sem nome"
            addr = p.get("address") or "sem endereço"
            rating = p.get("rating")
            if rating is not None:
                lines.append(f"- {title} ({rating}/5) - {addr}")
            else:
                lines.append(f"- {title} - {addr}")
        return "\n".join(lines)

    def _get_api_key(self) -> Optional[str]:
        api_key = self.config.get("apiKey")
        if not api_key or "ENV_" in str(api_key):
            api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        return api_key

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

    def _geocode_text(self, api_key: str, text: str) -> Optional[str]:
        query = self._sanitize_text(text)
        if not query:
            return None
        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": query, "key": api_key},
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
        api_key: str,
        query: str,
        location_bias: Optional[str],
        radius: int,
        place_type: Optional[str],
        open_now: bool,
    ) -> Dict[str, Any]:
        request_params: Dict[str, Any] = {
            "query": query,
            "key": api_key,
            "language": self.config.get("defaults", {}).get("language", "pt-BR"),
            "region": self.config.get("defaults", {}).get("region", "BR"),
        }
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
            timeout=10,
        )
        data = response.json()
        status = data.get("status")
        if response.status_code != 200 or (status not in {"OK", "ZERO_RESULTS"}):
            return {
                "ok": False,
                "error": "GOOGLE_MAPS_API_ERROR",
                "message": data.get("error_message") or status or f"HTTP {response.status_code}",
            }

        places = [self._normalize_place(item, rank=i + 1) for i, item in enumerate(data.get("results") or [])]
        return {
            "ok": True,
            "status": "empty" if status == "ZERO_RESULTS" else "success",
            "places": places,
        }

    def _resolve_location_bias(
        self,
        api_key: str,
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
            geocoded = self._geocode_text(api_key, near)
            if geocoded:
                return geocoded

        if city:
            geocoded = self._geocode_text(api_key, city)
            if geocoded:
                return geocoded

        return self._extract_coords_from_context(context)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        if action != "search":
            return self._result(
                ok=False,
                status="error",
                text=f"Ação desconhecida para maps_search: {action_id}",
                error="UNKNOWN_ACTION",
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
                text="Informe pelo menos um query, category ou city para a busca no Maps.",
                error="MISSING_QUERY",
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
            return self._result(
                ok=False,
                status="error",
                text="Google Maps API Key não configurada. Defina GOOGLE_MAPS_API_KEY.",
                error="MISSING_CONFIG",
                message="Google Maps API Key not configured.",
                missing_fields=["apiKey"],
            )

        location_bias = self._resolve_location_bias(api_key, near, city, context)
        max_variants = self._to_int(params.get("max_variants"), default=3, min_value=1, max_value=5)
        query_variants = [base_query] if mode == "standard" else self._build_variants(base_query, category, city, max_variants)

        try:
            merged: List[Dict[str, Any]] = []
            seen_place_ids = set()
            for variant in query_variants:
                result = self._search_google_places(
                    api_key=api_key,
                    query=variant,
                    location_bias=location_bias,
                    radius=radius,
                    place_type=place_type or None,
                    open_now=open_now,
                )
                if not result.get("ok"):
                    return self._result(
                        ok=False,
                        status="error",
                        text=f"Erro na API do Google Maps: {result.get('message')}",
                        error=result.get("error", "GOOGLE_MAPS_API_ERROR"),
                        message=result.get("message"),
                        provider="google_maps",
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
            text = self._summary(base_query, city, merged, mode)
            return self._result(
                ok=True,
                status=status,
                text=text,
                provider="google_maps",
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
                text=f"Erro na execução da busca do Maps: {str(e)}",
                error="MAPS_SEARCH_EXCEPTION",
                message=str(e),
                provider="google_maps",
            )
