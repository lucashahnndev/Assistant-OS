from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional

from ..ingestion import ExampleIngestor
from ..vector_store import ContextVectorStore


class ExampleRetriever:
    def __init__(self, *, vector_store: ContextVectorStore, ingestor: ExampleIngestor):
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
        allowed_set = set(allowed_actions or [])
        filtered: List[Dict[str, Any]] = []
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            action_id = str(metadata.get("action_id") or "").strip()
            if allowed_set and action_id and action_id not in allowed_set:
                continue
            filtered.append(row)
        return self._group_rows(filtered, max_results=target.max_results)

    @staticmethod
    def _group_rows(rows: List[Dict[str, Any]], max_results: int) -> List[Dict[str, Any]]:
        grouped: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            key = str(metadata.get("action_id") or metadata.get("title") or row.get("id") or "example")
            if key not in grouped:
                grouped[key] = {
                    "title": str(metadata.get("title") or metadata.get("action_id") or "Example"),
                    "content": str(row.get("content") or ""),
                    "source": metadata.get("source_file") or "examples",
                    "metadata": metadata,
                    "score": float(row.get("score") or 0.0),
                    "timestamp": metadata.get("updated_at"),
                    "provenance": ["examples"],
                }
            elif len(grouped[key]["content"]) < 750:
                grouped[key]["content"] = f"{grouped[key]['content']} {row.get('content')}".strip()
                grouped[key]["score"] = max(float(grouped[key]["score"]), float(row.get("score") or 0.0))
        items = list(grouped.values())
        items.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return [ExampleRetriever._normalize(item) for item in items[: max(1, int(max_results or 1))]]

    @staticmethod
    def _normalize(item: Dict[str, Any]) -> Dict[str, Any]:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        action_id = str(metadata.get("action_id") or "").strip()
        capability_id = str(metadata.get("capability_id") or "").strip()
        example_type = str(metadata.get("example_type") or "").strip()
        content = " ".join(str(item.get("content") or "").split())
        normalized = (
            f"example: use {action_id or capability_id or item.get('title')} correctly. "
            f"type: {example_type or 'usage'}. content: {content[:240]}"
        )
        return {**item, "content": normalized}
