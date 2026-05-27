from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .models import EvidenceItem


class EvidenceBuilder:
    """Normalizes retrieval payloads into compact, prompt-ready evidence units."""

    def __init__(self, content_limit: int = 420):
        self.content_limit = max(120, int(content_limit or 420))
        self.domain_limits = {
            "external_knowledge": 320,
            "mcp_resources": 360,
            "examples": 280,
            "policies": 360,
        }

    def build(self, domain: str, raw_items: Iterable[Dict[str, Any]]) -> List[EvidenceItem]:
        evidence: List[EvidenceItem] = []
        for raw in raw_items or []:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or raw.get("name") or domain.replace("_", " ").title()).strip()
            content = self._compact_content(
                raw.get("content") or raw.get("summary") or raw.get("description") or "",
                limit=self.domain_limits.get(domain, self.content_limit),
            )
            if not content:
                continue
            provenance = raw.get("provenance")
            if not isinstance(provenance, list):
                provenance = [str(provenance)] if provenance else []
            evidence.append(
                EvidenceItem(
                    domain=domain,
                    title=title,
                    content=content,
                    source=str(raw.get("source") or raw.get("origin") or "unknown"),
                    metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
                    score=self._coerce_score(raw.get("score")),
                    timestamp=self._coerce_timestamp(raw.get("timestamp")),
                    provenance=[str(item) for item in provenance if str(item).strip()],
                )
            )
        evidence.sort(key=lambda item: item.score, reverse=True)
        return evidence

    def format_for_prompt(self, evidence_items: List[EvidenceItem], max_items: int = 6) -> str:
        lines: List[str] = []
        for item in (evidence_items or [])[: max(1, int(max_items or 1))]:
            lines.append(f"[EVIDENCE: {item.domain}]")
            lines.append(f"title: {item.title}")
            lines.append(f"content: {item.content}")
            lines.append(f"source: {item.source}")
            if item.score:
                lines.append(f"score: {item.score:.2f}")
            if item.timestamp:
                lines.append(f"timestamp: {item.timestamp}")
            if item.provenance:
                lines.append(f"provenance: {', '.join(item.provenance)}")
            lines.append("")
        return "\n".join(lines).strip()

    def _compact_content(self, content: Any, *, limit: int | None = None) -> str:
        max_chars = self.content_limit if limit is None else max(120, int(limit))
        text = " ".join(str(content or "").strip().split())
        if len(text) <= max_chars:
            return text
        clipped = text[:max_chars].rstrip()
        return f"{clipped}..."

    @staticmethod
    def _coerce_score(value: Any) -> float:
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _coerce_timestamp(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None
