from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..ingestion import AgentExperienceIngestor
from ..vector_store import ContextVectorStore


class AgentExperienceRetriever:
    def __init__(self, *, vector_store: ContextVectorStore, ingestor: AgentExperienceIngestor):
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
        self.last_ingestion_stats = self.ingestor.promote_session_experience(session)
        rows = self.vector_store.query(self.ingestor.collection_name, query, n_results=max(target.max_results * 4, 6))
        items: List[Dict[str, Any]] = []
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            content = " ".join(str(row.get("content") or "").split())
            experience_type = str(metadata.get("experience_type") or "lesson").strip()
            recovery_type = str(metadata.get("recovery_type") or "advisory").strip()
            items.append(
                {
                    "title": str(metadata.get("title") or "Operational Experience"),
                    "content": (
                        f"lesson: {content[:240]} "
                        f"(type: {experience_type}; recovery: {recovery_type})"
                    ).strip(),
                    "source": f"agent_experience:{row.get('id')}",
                    "metadata": metadata,
                    "score": float(row.get("score") or 0.0),
                    "timestamp": metadata.get("updated_at"),
                    "provenance": ["agent_experience"],
                }
            )
        items.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return items[: target.max_results]
