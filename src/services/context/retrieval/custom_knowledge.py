from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..ingestion import CustomKnowledgeIngestor
from ..vector_store import ContextVectorStore
from .external_knowledge import CustomVisibilityResolver


class CustomKnowledgeRetriever:
    def __init__(self, *, vector_store: ContextVectorStore, ingestor: CustomKnowledgeIngestor):
        self.vector_store = vector_store
        self.ingestor = ingestor
        self.last_ingestion_stats: Dict[str, int] = {}

    def retrieve(
        self,
        *,
        query: str,
        session,
        capability_registry=None,
        allowed_actions: Optional[List[str]] = None,
        target,
    ) -> List[Dict[str, Any]]:
        result = self.ingestor.ingest_if_needed()
        self.last_ingestion_stats = {
            "evaluated": int(result.get("chunks", 0)),
            "accepted": int(result.get("chunks", 0)),
            "suppressed_noise": 0,
            "suppressed_duplicates": 0,
        }
        rows = self.vector_store.query(self.ingestor.collection_name, query, n_results=max(target.max_results * 4, 6))
        items: List[Dict[str, Any]] = []
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if not self._is_visible(metadata, session):
                continue
            content = " ".join(str(row.get("content") or "").split())
            items.append(
                {
                    "title": str(metadata.get("title") or "Custom Knowledge"),
                    "content": f"custom: {content[:260]}",
                    "source": str(metadata.get("source_file") or row.get("id") or "custom_knowledge"),
                    "metadata": metadata,
                    "score": float(row.get("score") or 0.0),
                    "timestamp": metadata.get("updated_at"),
                    "provenance": ["custom_knowledge"],
                }
            )
        items.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return items[: target.max_results]

    @staticmethod
    def _is_visible(metadata: Dict[str, Any], session) -> bool:
        principal_id = CustomVisibilityResolver.resolve_principal_id(session)
        tenant_id = CustomVisibilityResolver.resolve_tenant_id(session)
        workspace_id = CustomVisibilityResolver.resolve_workspace_id(session)
        visibility = str(metadata.get("policy_visibility") or "tenant").strip().lower()
        scope = str(metadata.get("knowledge_scope") or "workspace").strip().lower()
        if visibility == "principal" and metadata.get("principal_id") and str(metadata.get("principal_id")) != principal_id:
            return False
        if visibility == "tenant" and metadata.get("tenant_id") and str(metadata.get("tenant_id")) != tenant_id:
            return False
        if scope == "principal" and metadata.get("principal_id") and str(metadata.get("principal_id")) != principal_id:
            return False
        if scope == "tenant" and metadata.get("tenant_id") and str(metadata.get("tenant_id")) != tenant_id:
            return False
        if scope == "workspace" and metadata.get("origin") and workspace_id and str(metadata.get("origin")) != workspace_id:
            return False
        return True
