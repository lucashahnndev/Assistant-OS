from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from ..models import RAGChunk, RAGChunkMetadata
from ..vector_store import ContextVectorStore


class UserMemoryIngestor:
    collection_name = "user_memory"

    def __init__(self, *, vector_store: ContextVectorStore):
        self.vector_store = vector_store

    def promote_session_memory(self, session, principal_id: str, tenant_id: str) -> Dict[str, int]:
        chunks: List[RAGChunk] = []
        for entry in getattr(session, "memory", None) or []:
            is_valid, _ = self._validate_entry(entry)
            if not is_valid:
                continue
            chunks.append(self._chunk_from_entry(entry=entry, principal_id=principal_id, tenant_id=tenant_id))
        count = self.vector_store.upsert_documents(self.collection_name, chunks)
        return {"promoted": count}

    def _chunk_from_entry(self, *, entry: Dict[str, object], principal_id: str, tenant_id: str) -> RAGChunk:
        updated_at = self._coerce_timestamp(entry.get("updated_at") or entry.get("timestamp"))
        created_at = self._coerce_timestamp(entry.get("created_at") or entry.get("timestamp") or updated_at)
        memory_id = str(entry.get("memory_id") or entry.get("id") or "")
        content = str(entry.get("content") or "").strip()
        title = str(entry.get("title") or entry.get("category") or "user_memory").strip()
        trust_level = str(entry.get("trust_level") or self._trust_from_confidence(entry.get("confidence"))).strip()
        source_type = str(entry.get("source_type") or "session_memory").strip()
        chunk_id = hashlib.sha1(
            f"{self.collection_name}|{principal_id}|{tenant_id}|{memory_id or content}".encode("utf-8")
        ).hexdigest()
        metadata = RAGChunkMetadata(
            doc_type="user_memory",
            collection_type=self.collection_name,
            capability_id="",
            action_id="",
            principal_id=principal_id,
            tenant_id=tenant_id,
            source_file=f"session_memory:{principal_id}",
            created_at=created_at,
            updated_at=updated_at,
            trust_level=trust_level,
            source_type=source_type,
            embedding_version=self.vector_store.embedding_version,
            title=title,
            chunk_index=0,
            total_chunks=1,
        )
        fact_prefix = f"Fact: {title}. " if title and title != "user_memory" else "Fact: "
        return RAGChunk(chunk_id=chunk_id, content=f"{fact_prefix}{content}".strip(), metadata=metadata)

    @staticmethod
    def _validate_entry(entry: object) -> Tuple[bool, str]:
        if not isinstance(entry, dict):
            return False, "not_dict"
        status = str(entry.get("status") or "").strip().lower()
        if status != "accepted":
            return False, "not_accepted"
        if entry.get("is_deleted"):
            return False, "deleted"
        content = str(entry.get("content") or "").strip()
        if not content:
            return False, "empty"
        if len(content) < 6:
            return False, "too_short"
        return True, "ok"

    @staticmethod
    def _coerce_timestamp(value: object) -> str:
        text = str(value or "").strip()
        if text:
            return text
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _trust_from_confidence(confidence: object) -> str:
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            value = 0.7
        if value >= 0.85:
            return "high"
        if value >= 0.6:
            return "medium"
        return "low"
