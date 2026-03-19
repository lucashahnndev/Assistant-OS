from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional

from ..ingestion import PolicyIngestor
from ..vector_store import ContextVectorStore


class PolicyRetriever:
    def __init__(self, *, vector_store: ContextVectorStore, ingestor: PolicyIngestor):
        self.vector_store = vector_store
        self.ingestor = ingestor

    def retrieve(
        self,
        *,
        query: str,
        session,
        capability_registry=None,
        allowed_actions: Optional[List[str]] = None,
        target,
    ) -> List[Dict[str, Any]]:
        self.ingestor.ingest_if_needed()
        rows = self.vector_store.query(self.ingestor.collection_name, query, n_results=max(target.max_results * 4, 6))
        return self._group_rows(rows, max_results=target.max_results)

    @staticmethod
    def _group_rows(rows: List[Dict[str, Any]], max_results: int) -> List[Dict[str, Any]]:
        grouped: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            key = str(metadata.get("policy_id") or metadata.get("title") or row.get("id") or "policy")
            if key not in grouped:
                grouped[key] = {
                    "title": str(metadata.get("title") or metadata.get("policy_id") or "Policy"),
                    "content": str(row.get("content") or ""),
                    "source": metadata.get("source_file") or "policies",
                    "metadata": metadata,
                    "score": float(row.get("score") or 0.0),
                    "timestamp": metadata.get("updated_at"),
                    "provenance": ["policies"],
                }
            elif len(grouped[key]["content"]) < 900:
                grouped[key]["content"] = f"{grouped[key]['content']} {row.get('content')}".strip()
                grouped[key]["score"] = max(float(grouped[key]["score"]), float(row.get("score") or 0.0))
        items = list(grouped.values())
        items.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return [PolicyRetriever._normalize(item) for item in items[: max(1, int(max_results or 1))]]

    @staticmethod
    def _normalize(item: Dict[str, Any]) -> Dict[str, Any]:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        content = " ".join(str(item.get("content") or "").split())
        rule_group = str(metadata.get("rule_group") or "").strip()
        scope_hint = str(metadata.get("scope_hint") or "").strip()
        normalized = (
            f"policy: {item.get('title')}. rule_group: {rule_group or 'general'}. "
            f"scope: {scope_hint or 'system'}. summary: {content[:260]}"
        )
        return {**item, "content": normalized}
