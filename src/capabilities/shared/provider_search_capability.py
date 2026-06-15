from __future__ import annotations

from time import perf_counter
from typing import Any, Dict, List, Optional

from ..base import CapabilityBase
from .error_contract import error_envelope, success_envelope
from .search_providers.base import SearchProvider, SearchRequest


class ProviderSearchCapabilityBase(CapabilityBase):
    CAPABILITY_NAME = "provider_search"
    ACTION_HANDLER = "query"
    NAMESPACE = "provider.search"
    PROVIDER_LABEL = "provider"
    DEFAULT_LIMIT = 5
    DEFAULT_LANGUAGE = "en"

    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = self.NAMESPACE

    @property
    def name(self) -> str:
        return self.CAPABILITY_NAME

    @property
    def actions(self) -> List[str]:
        return [self.ACTION_HANDLER]

    @staticmethod
    def _clamp_limit(value: Any, default: int = 5) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(1, min(n, 20))

    @staticmethod
    def _clamp_recency_days(value: Any) -> int:
        try:
            n = int(value)
        except Exception:
            n = 0
        return max(0, min(n, 3650))

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
        out: List[str] = []
        for item in value:
            val = str(item or "").strip().lower()
            if val:
                out.append(val)
        return out

    @staticmethod
    def _country_from_language(language: str) -> str:
        raw = str(language or "").strip().replace("_", "-")
        if "-" in raw:
            cc = raw.split("-", 1)[1].strip()
            if len(cc) == 2:
                return cc.upper()
        return ""

    @staticmethod
    def _resolve_location(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        loc = params.get("location")
        if not isinstance(loc, dict):
            return None
        out = {
            "city": str(loc.get("city") or "").strip() or None,
            "state": str(loc.get("state") or "").strip() or None,
            "country": str(loc.get("country") or "").strip() or None,
            "latitude": loc.get("latitude") if loc.get("latitude") is not None else loc.get("lat"),
            "longitude": loc.get("longitude") if loc.get("longitude") is not None else loc.get("lon"),
        }
        if not any(v is not None and v != "" for v in out.values()):
            return None
        return out

    def _build_provider(self) -> SearchProvider:
        raise NotImplementedError

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        _ = context
        started = perf_counter()
        action = action_id.split(".")[-1]
        if action != self.ACTION_HANDLER:
            return error_envelope(
                provider=self.PROVIDER_LABEL,
                error_code="UNKNOWN_ACTION",
                error_message=f"Unknown action: {action_id}",
                retryable=False,
                elapsed=int((perf_counter() - started) * 1000),
                result_summary=f"Unknown action: {action_id}",
                diagnostics={
                    "provider": self.PROVIDER_LABEL,
                    "action_id": action_id,
                    "query": params.get("query") or params.get("q") or "",
                    "parse_status": "unsupported_action",
                },
            )

        query = self._resolve_query(params)
        if not query:
            payload = error_envelope(
                provider=self.PROVIDER_LABEL,
                error_code="MISSING_QUERY",
                error_message="Missing required parameter: query",
                retryable=False,
                elapsed=int((perf_counter() - started) * 1000),
                result_summary="Missing required parameter: query",
                requires_followup=True,
                next_step_context={"suggestion": "Provide a search query."},
                diagnostics={
                    "provider": self.PROVIDER_LABEL,
                    "parse_status": "missing_query",
                },
            )
            payload.update(
                {
                    "query": "",
                    "count": 0,
                    "results": [],
                    "best": None,
                    "structured_result": {"query": "", "count": 0, "results": [], "best": None, "providers_tried": []},
                }
            )
            return payload

        defaults = self.config.get("defaults") if isinstance(self.config.get("defaults"), dict) else {}
        limit = self._clamp_limit(params.get("limit") or defaults.get("limit") or self.DEFAULT_LIMIT, default=self.DEFAULT_LIMIT)
        language = str(params.get("language") or defaults.get("language") or self.DEFAULT_LANGUAGE).strip() or self.DEFAULT_LANGUAGE
        recency_days = self._clamp_recency_days(params.get("recency_days") or defaults.get("recency_days") or 0)

        request = SearchRequest(
            query=query,
            limit=limit,
            recency_days=recency_days,
            domains_allow=self._to_domains(params.get("domains_allow")),
            domains_deny=self._to_domains(params.get("domains_deny")),
            language=language,
            country=self._country_from_language(language),
            location=self._resolve_location(params),
        )

        try:
            provider = self._build_provider()
            response = provider.search(request)
            rows = []
            for idx, item in enumerate(response.results, start=1):
                payload = item.to_payload()
                payload["rank"] = idx
                snippet = str(payload.get("snippet") or "").strip()
                payload["excerpt"] = snippet
                payload["content"] = snippet
                rows.append(payload)

            envelope = success_envelope(
                provider=self.PROVIDER_LABEL,
                elapsed=int((perf_counter() - started) * 1000),
                warnings=list(response.warnings or []),
                result_summary=(
                    f"Found {len(rows)} result(s) for '{query}'."
                    if rows
                    else f"No results found for '{query}'."
                ),
                structured_result={
                    "query": query,
                    "count": len(rows),
                    "results": rows,
                    "best": rows[0] if rows else None,
                    "providers_tried": [provider.name],
                },
                artifacts=[],
                attachment_delivery={"status": "none", "confirmed": False},
                freshness={
                    "type": "live",
                    "status": "fresh" if rows else "empty",
                    "recency_days": recency_days,
                },
                truncated=bool(limit and len(rows) >= limit),
                requires_followup=not bool(rows),
                next_step_context=(
                    {"suggestion": "Broaden the query or change the recency filter."}
                    if not rows
                    else {}
                ),
                diagnostics={
                    "provider": self.PROVIDER_LABEL,
                    "providers_tried": [provider.name],
                    "query": query,
                    "limit": limit,
                    "recency_days": recency_days,
                    "parse_status": "ok",
                },
            )
            envelope.update(
                {
                    "query": query,
                    "count": len(rows),
                    "results": rows,
                    "best": rows[0] if rows else None,
                    "providers_tried": [provider.name],
                }
            )
            if not rows:
                envelope["status"] = "empty"
            return envelope
        except Exception as exc:
            payload = error_envelope(
                provider=self.PROVIDER_LABEL,
                error_code="PROVIDER_EXECUTION_ERROR",
                error_message=str(exc),
                retryable=True,
                elapsed=int((perf_counter() - started) * 1000),
                result_summary=f"Search provider '{provider.name if 'provider' in locals() else self.PROVIDER_LABEL}' failed.",
                diagnostics={
                    "provider": self.PROVIDER_LABEL,
                    "query": query,
                    "limit": limit,
                    "recency_days": recency_days,
                    "parse_status": "provider_exception",
                },
            )
            payload.update(
                {
                    "query": query,
                    "count": 0,
                    "results": [],
                    "best": None,
                    "structured_result": {
                        "query": query,
                        "count": 0,
                        "results": [],
                        "best": None,
                        "providers_tried": [provider.name] if "provider" in locals() else [],
                    },
                }
            )
            return payload
