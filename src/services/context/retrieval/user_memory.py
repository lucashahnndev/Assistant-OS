from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..ingestion import UserMemoryIngestor
from ..vector_store import ContextVectorStore


class UserMemoryRetriever:
    def __init__(self, *, vector_store: ContextVectorStore, ingestor: UserMemoryIngestor):
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
        principal_id = self.resolve_principal_id(session)
        tenant_id = self.resolve_tenant_id(session)
        self.ingestor.promote_session_memory(session, principal_id=principal_id, tenant_id=tenant_id)
        raw = self.vector_store.query(
            self.ingestor.collection_name,
            query,
            n_results=max(target.max_results * 3, 4),
            where={"principal_id": principal_id},
        )
        items: List[Dict[str, Any]] = []
        for row in raw:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if tenant_id and str(metadata.get("tenant_id") or tenant_id) != tenant_id:
                continue
            content = " ".join(str(row.get("content") or "").split())
            items.append(
                {
                    "title": str(metadata.get("title") or "User Memory"),
                    "content": f"fact: {content[:260]}",
                    "source": f"user_memory:{row.get('id')}",
                    "metadata": metadata,
                    "score": float(row.get("score") or 0.0),
                    "timestamp": metadata.get("updated_at"),
                    "provenance": ["user_memory"],
                }
            )
        items.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return items[: target.max_results]

    @staticmethod
    def resolve_principal_id(session) -> str:
        context = getattr(session, "context", None) or {}
        for key in ("principal_id", "user_id", "sender_id", "user_name"):
            value = str(context.get(key) or "").strip()
            if value:
                return value
        session_id = str(getattr(session, "session_id", "") or "").strip()
        return session_id or "anonymous"

    @staticmethod
    def resolve_tenant_id(session) -> str:
        context = getattr(session, "context", None) or {}
        value = str(context.get("tenant_id") or "").strip()
        return value or "default"
