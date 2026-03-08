import logging
import re
from time import perf_counter
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from ..base import SkillBase
from ..shared.chunking import chunk_text
from ..shared.error_contract import error_envelope, success_envelope
from ..shared.retrieval import fetch_and_read
from ..shared.search_providers import SearchRouter

logger = logging.getLogger("WebSearchSkill")


class WebSearchSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "web"
        self._router = SearchRouter(config=self._router_config())

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def actions(self) -> List[str]:
        return ["discover"]

    def _router_config(self) -> Dict[str, Any]:
        cfg = self.config if isinstance(self.config, dict) else {}
        router_cfg = cfg.get("search_router") if isinstance(cfg.get("search_router"), dict) else {}
        defaults = cfg.get("defaults") if isinstance(cfg.get("defaults"), dict) else {}
        out = dict(router_cfg)
        if "timeout_ms" not in out and defaults.get("timeout_ms") is not None:
            out["timeout_ms"] = defaults.get("timeout_ms")
        if "retries" not in out and defaults.get("retries") is not None:
            out["retries"] = defaults.get("retries")
        return out

    @staticmethod
    def _clamp_limit(value: Any, default: int = 5) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(1, min(n, 20))

    @staticmethod
    def _clamp_knowledge_limit(value: Any, default: int = 2) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(1, min(n, 8))

    @staticmethod
    def _clamp_chars(value: Any, default: int = 2500) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(500, min(n, 12000))

    @staticmethod
    def _clamp_chunk_size(value: Any, default: int = 700) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(200, min(n, 2000))

    @staticmethod
    def _clamp_chunk_overlap(value: Any, default: int = 100) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(0, min(n, 500))

    @staticmethod
    def _clamp_recency_days(value: Any) -> int:
        try:
            n = int(value)
        except Exception:
            return 0
        return max(0, min(n, 3650))

    @staticmethod
    def _sanitize_text(text: Any) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    @staticmethod
    def _resolve_query(params: Dict[str, Any]) -> str:
        for key in ("query", "search_query", "searchQuery", "q", "term", "text"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _to_domains(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        domains: List[str] = []
        for item in value:
            val = str(item or "").strip().lower()
            if not val:
                continue
            if val.startswith("http://") or val.startswith("https://"):
                val = (urlsplit(val).netloc or "").lower()
            val = val.split(":", 1)[0]
            if val:
                domains.append(val)
        return domains

    @staticmethod
    def _normalize_locale(locale: str) -> str:
        raw = str(locale or "").strip().replace("_", "-")
        if not raw:
            return "en"
        return raw

    @staticmethod
    def _country_from_locale(locale: str) -> str:
        value = str(locale or "").strip()
        if "-" in value:
            maybe = value.split("-", 1)[1].strip()
            if len(maybe) == 2:
                return maybe.upper()
        return ""

    @staticmethod
    def _extract_location_from_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(data, dict):
            return None
        location = data.get("location") if isinstance(data.get("location"), dict) else data
        if not isinstance(location, dict):
            return None
        city = str(location.get("city") or "").strip()
        state = str(location.get("state") or "").strip()
        country = str(location.get("country") or "").strip()
        lat = location.get("latitude")
        if lat is None:
            lat = location.get("lat")
        lon = location.get("longitude")
        if lon is None:
            lon = location.get("lon")
        if not any([city, state, country, lat is not None and lon is not None]):
            return None
        return {
            "city": city or None,
            "state": state or None,
            "country": country or None,
            "latitude": lat,
            "longitude": lon,
        }

    def _resolve_language(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        candidates = [
            params.get("language"),
            params.get("lang"),
            params.get("locale"),
            context.get("language"),
            context.get("lang"),
            context.get("locale"),
        ]
        session = context.get("session")
        if session is not None and hasattr(session, "context") and isinstance(session.context, dict):
            candidates.extend(
                [
                    session.context.get("user_language"),
                    session.context.get("language"),
                    session.context.get("locale"),
                ]
            )

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return self._normalize_locale(candidate)

        kernel = self.kernel
        cfg_manager = getattr(kernel, "config_manager", None) if kernel else None
        if cfg_manager and hasattr(cfg_manager, "get_i18n_config"):
            i18n_cfg = cfg_manager.get_i18n_config()
            if isinstance(i18n_cfg, dict):
                default_locale = str(i18n_cfg.get("default_locale") or "").strip()
                if default_locale:
                    return self._normalize_locale(default_locale)

        defaults = self.config.get("defaults", {}) if isinstance(self.config, dict) else {}
        language = self._normalize_locale(str(defaults.get("language") or "en"))
        if language in {"en", "en-us", "en-gb"}:
            loc_hint = self._extract_location_from_dict(context) or {}
            cc = str(loc_hint.get("country") or "").strip().lower()
            if cc in {"brazil", "brasil", "br"}:
                return "pt-BR"
        return language

    def _resolve_location(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        # 1) explicit params from app/web call
        loc = self._extract_location_from_dict(params)
        if loc:
            return loc

        # 2) direct context payload from web app
        loc = self._extract_location_from_dict(context)
        if loc:
            return loc

        # 3) session context
        session = context.get("session")
        if session is not None and hasattr(session, "context") and isinstance(session.context, dict):
            loc = self._extract_location_from_dict(session.context)
            if loc:
                return loc

        # 4) fallback from config manager location default
        kernel = self.kernel
        cfg_manager = getattr(kernel, "config_manager", None) if kernel else None
        if cfg_manager and hasattr(cfg_manager, "get_location_config"):
            loc_cfg = cfg_manager.get_location_config()
            if isinstance(loc_cfg, dict):
                default = loc_cfg.get("default") if isinstance(loc_cfg.get("default"), dict) else {}
                loc = self._extract_location_from_dict(default)
                if loc:
                    return loc
        return {}

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    @classmethod
    def _resolve_mode(cls, requested_mode: Any) -> str:
        mode = str(requested_mode or "links").strip().lower()
        if mode not in {"links", "knowledge", "auto"}:
            mode = "links"
        if mode == "auto":
            return "links"
        return mode

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        started = perf_counter()
        action = action_id.split(".")[-1]
        query = self._resolve_query(params)
        limit = self._clamp_limit(
            params.get("limit")
            or params.get("max_results")
            or params.get("maxResults")
            or self.config.get("defaults", {}).get("limit", 5),
            default=5,
        )
        requested_mode = params.get("mode") or self.config.get("defaults", {}).get("mode", "links")
        mode = self._resolve_mode(requested_mode)
        knowledge_limit = self._clamp_knowledge_limit(
            params.get("knowledge_limit") or self.config.get("defaults", {}).get("knowledge_limit", 2),
            default=2,
        )
        max_chars_per_doc = self._clamp_chars(
            params.get("max_chars_per_doc") or self.config.get("defaults", {}).get("max_chars_per_doc", 2500),
            default=2500,
        )
        chunk_size = self._clamp_chunk_size(
            params.get("chunk_size") or self.config.get("defaults", {}).get("chunk_size", 700),
            default=700,
        )
        chunk_overlap = self._clamp_chunk_overlap(
            params.get("chunk_overlap") or self.config.get("defaults", {}).get("chunk_overlap", 100),
            default=100,
        )
        recency_days = self._clamp_recency_days(params.get("recency_days"))
        domains_allow = self._to_domains(params.get("domains_allow"))
        domains_deny = self._to_domains(params.get("domains_deny"))
        language = self._resolve_language(params, context)
        location = self._resolve_location(params, context)
        country = str(location.get("country") or "").strip().upper() if location else ""
        if not country:
            country = self._country_from_locale(language)

        if not query:
            payload = error_envelope(
                provider="search_router",
                error_code="MISSING_QUERY",
                error_message="Missing query for web discovery.",
                retryable=False,
                elapsed=max(1, int((perf_counter() - started) * 1000)),
            )
            payload.update(
                {
                    "query": "",
                    "mode": mode,
                    "count": 0,
                    "results": [],
                    "knowledge_docs": [],
                    "chunks": [],
                }
            )
            return payload

        if action != "discover":
            payload = error_envelope(
                provider="search_router",
                error_code="UNKNOWN_ACTION",
                error_message=f"Unknown web_search action: {action_id}",
                retryable=False,
                elapsed=max(1, int((perf_counter() - started) * 1000)),
            )
            payload.update(
                {
                    "query": query,
                    "mode": mode,
                    "count": 0,
                    "results": [],
                    "knowledge_docs": [],
                    "chunks": [],
                }
            )
            return payload

        routed = self._router.search(
            query=query,
            limit=limit,
            recency_days=recency_days,
            domains_allow=domains_allow,
            domains_deny=domains_deny,
            language=language,
            country=country,
            location=location,
        )
        results = routed.get("results") if isinstance(routed.get("results"), list) else []
        warnings: List[str] = [str(w) for w in (routed.get("warnings") or []) if str(w).strip()]
        provider = str(routed.get("provider") or "search_router")
        providers_tried = routed.get("providers_tried") if isinstance(routed.get("providers_tried"), list) else []

        knowledge_docs: List[Dict[str, Any]] = []
        chunks: List[Dict[str, Any]] = []

        if mode == "knowledge" and results:
            candidates = results[:knowledge_limit]
            for entry in candidates:
                url = str(entry.get("url") or "").strip()
                extraction = fetch_and_read(
                    url=url,
                    mode="main",
                    max_chars=max_chars_per_doc,
                    timeout_ms=10000,
                    retries=1,
                )
                if not extraction.get("ok"):
                    warnings.append(
                        f"{url or 'sem_url'}: {extraction.get('error_code') or extraction.get('error') or extraction.get('message') or 'erro desconhecido'}"
                    )
                    continue

                content = self._sanitize_text(extraction.get("text_md"))
                if not content:
                    warnings.append(f"{url or 'sem_url'}: conteúdo vazio após limpeza.")
                    continue

                doc_chunks = chunk_text(content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
                doc = {
                    "rank": entry.get("rank"),
                    "title": extraction.get("title") or entry.get("title") or "Untitled",
                    "url": url,
                    "excerpt": self._truncate(content, 280),
                    "content": content,
                    "chunks": doc_chunks,
                    "source": entry.get("source", provider),
                    "provider": entry.get("provider", provider),
                }
                knowledge_docs.append(doc)

                for chunk in doc_chunks:
                    chunks.append(
                        {
                            "doc_rank": doc.get("rank"),
                            "title": doc.get("title"),
                            "url": url,
                            "chunk_id": chunk.get("id"),
                            "error_details": chunk.get("text"),
                            "start": chunk.get("start"),
                            "end": chunk.get("end"),
                        }
                    )

        elapsed = max(1, int((perf_counter() - started) * 1000))
        payload = success_envelope(provider=provider, elapsed=elapsed, warnings=warnings)
        payload.update(
            {
                "query": query,
                "query_original": query,
                "queries_executed": [query],
                "providers_tried": providers_tried,
                "language": language,
                "location": location if location else None,
                "mode": mode,
                "count": len(results),
                "results": results,
                "best": results[0] if results else None,
                "knowledge_docs": knowledge_docs,
                "chunks": chunks,
            }
        )
        if not results:
            payload["status"] = "empty"
        return payload
