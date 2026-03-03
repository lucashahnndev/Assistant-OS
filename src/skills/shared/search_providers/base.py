from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SearchRequest:
    query: str
    limit: int
    recency_days: int
    domains_allow: List[str]
    domains_deny: List[str]
    language: str = "en"
    country: str = ""
    location: Optional[Dict[str, Any]] = None


@dataclass
class SearchResultItem:
    title: str
    url: str
    snippet: str
    source: str
    provider: str
    published_at: Optional[str] = None
    status_code: Optional[int] = None
    confidence_score: float = 0.0
    rank: int = 0

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "rank": int(self.rank),
            "title": str(self.title or "Untitled").strip(),
            "snippet": str(self.snippet or "").strip(),
            "url": str(self.url or "").strip(),
            "source": str(self.source or self.provider).strip(),
            "provider": str(self.provider or "").strip(),
            "confidenceScore": float(max(0.0, min(1.0, self.confidence_score))),
        }
        if self.published_at:
            payload["published_at"] = self.published_at
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        return payload


@dataclass
class SearchResponse:
    results: List[SearchResultItem]
    warnings: List[str]


class SearchProvider:
    name = "provider"

    def search(self, request: SearchRequest) -> SearchResponse:
        raise NotImplementedError
