from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set

from ..ingestion import CapabilityKnowledgeIngestor
from ..vector_store import ContextVectorStore


class CapabilityKnowledgeRetriever:
    def __init__(self, *, vector_store: ContextVectorStore, ingestor: CapabilityKnowledgeIngestor):
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
        raw = self.vector_store.query(self.ingestor.collection_name, query, n_results=max(target.max_results * 4, 6))
        allowed_capability_ids = self._allowed_capability_ids(allowed_actions, capability_registry)
        filtered = []
        allowed_set = set(allowed_actions or [])
        for row in raw:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            action_id = str(metadata.get("action_id") or "").strip()
            capability_id = str(metadata.get("capability_id") or "").strip()
            if allowed_set and action_id and action_id not in allowed_set:
                continue
            if allowed_capability_ids and capability_id and capability_id not in allowed_capability_ids and not action_id:
                continue
            filtered.append(row)
        return self._group_results(filtered, target.max_results)

    @staticmethod
    def _allowed_capability_ids(allowed_actions: Optional[List[str]], capability_registry) -> Set[str]:
        if not allowed_actions or capability_registry is None or not hasattr(capability_registry, "get_action_metadata"):
            return set()
        capability_ids: Set[str] = set()
        for action_id in allowed_actions:
            meta = capability_registry.get_action_metadata(action_id)
            capability_id = str((meta or {}).get("capability_id") or "").strip()
            if capability_id:
                capability_ids.add(capability_id)
        return capability_ids

    @staticmethod
    def _group_results(rows: List[Dict[str, Any]], max_results: int) -> List[Dict[str, Any]]:
        grouped: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            key = str(metadata.get("action_id") or f"{metadata.get('capability_id', '')}:{metadata.get('doc_type', '')}")
            if key not in grouped:
                grouped[key] = {
                    "title": str(metadata.get("action_id") or metadata.get("title") or metadata.get("capability_id") or "Capability Knowledge"),
                    "content": row.get("content") or "",
                    "source": metadata.get("source_file") or "capability_knowledge",
                    "metadata": metadata,
                    "score": float(row.get("score") or 0.0),
                    "timestamp": metadata.get("updated_at"),
                    "provenance": ["capability_knowledge"],
                }
                continue
            if len(grouped[key]["content"]) < 900:
                grouped[key]["content"] = f"{grouped[key]['content']} {row.get('content')}".strip()
            grouped[key]["score"] = max(float(grouped[key]["score"]), float(row.get("score") or 0.0))
        items = list(grouped.values())
        items.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return [CapabilityKnowledgeRetriever._normalize_item(item) for item in items[: max(1, int(max_results or 1))]]

    @staticmethod
    def _normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        content = " ".join(str(item.get("content") or "").split())
        action_id = str(metadata.get("action_id") or "").strip()
        capability_id = str(metadata.get("capability_id") or "").strip()
        doc_type = str(metadata.get("doc_type") or "").strip()
        if action_id:
            parameters = CapabilityKnowledgeRetriever._extract_field(content, "Parameters:")
            risk = CapabilityKnowledgeRetriever._extract_field(content, "Risk:")
            description = CapabilityKnowledgeRetriever._extract_field(content, "Description:")
            normalized = f"capability: {capability_id or action_id}. action: {action_id}. description: {description or content[:240]}. parameters: {parameters or 'none'}. risk: {risk or 'unknown'}"
        else:
            normalized = f"capability: {capability_id or item.get('title')}. doc_type: {doc_type}. summary: {content[:280]}"
        return {**item, "content": normalized}

    @staticmethod
    def _extract_field(text: str, marker: str) -> str:
        lower_text = text.lower()
        lower_marker = marker.lower()
        if lower_marker not in lower_text:
            return ""
        start = lower_text.find(lower_marker) + len(lower_marker)
        end = lower_text.find(". ", start)
        if end == -1:
            end = len(text)
        return text[start:end].strip(" .")
