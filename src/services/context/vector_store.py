from __future__ import annotations

import hashlib
import math
import os
from typing import Any, Dict, Iterable, List, Optional

import chromadb

from utils.logging_config import get_logger

from .models import RAGChunk

logger = get_logger("ContextVectorStore")


class ContextVectorStore:
    """Typed vector storage for context domains with deterministic local embeddings."""

    def __init__(self, base_dir: Optional[str] = None, embedding_version: str = "ctx-hash-v1", dimensions: int = 96):
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.base_dir = base_dir or os.path.join(root_dir, "data", "context_rag")
        self.chroma_dir = os.path.join(self.base_dir, "chroma")
        os.makedirs(self.chroma_dir, exist_ok=True)
        self.embedding_version = embedding_version
        self.dimensions = max(32, int(dimensions or 96))
        self.client = chromadb.PersistentClient(path=self.chroma_dir)

    def replace_collection(self, collection_name: str, chunks: List[RAGChunk]) -> int:
        try:
            self.client.delete_collection(collection_name)
        except Exception:
            pass
        collection = self.client.get_or_create_collection(name=collection_name, metadata={"embedding_version": self.embedding_version})
        if not chunks:
            return 0
        collection.add(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.content for chunk in chunks],
            metadatas=[chunk.metadata.to_chroma() for chunk in chunks],
            embeddings=self.embed_texts(chunk.content for chunk in chunks),
        )
        return len(chunks)

    def upsert_documents(self, collection_name: str, chunks: List[RAGChunk]) -> int:
        if not chunks:
            return 0
        collection = self.client.get_or_create_collection(name=collection_name, metadata={"embedding_version": self.embedding_version})
        ids = [chunk.chunk_id for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        metadatas = [chunk.metadata.to_chroma() for chunk in chunks]
        embeddings = self.embed_texts(documents)
        if hasattr(collection, "upsert"):
            collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
            return len(chunks)
        try:
            existing = collection.get(ids=ids)
            existing_ids = set(existing.get("ids") or [])
        except Exception:
            existing_ids = set()
        new_rows = []
        update_rows = []
        for index, chunk_id in enumerate(ids):
            row = (chunk_id, documents[index], metadatas[index], embeddings[index])
            if chunk_id in existing_ids:
                update_rows.append(row)
            else:
                new_rows.append(row)
        if new_rows:
            collection.add(
                ids=[row[0] for row in new_rows],
                documents=[row[1] for row in new_rows],
                metadatas=[row[2] for row in new_rows],
                embeddings=[row[3] for row in new_rows],
            )
        for row in update_rows:
            collection.update(ids=[row[0]], documents=[row[1]], metadatas=[row[2]], embeddings=[row[3]])
        return len(chunks)

    def query(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        try:
            collection = self.client.get_collection(collection_name)
        except Exception:
            return []
        try:
            result = collection.query(
                query_embeddings=[self.embed_text(query_text)],
                n_results=max(1, int(n_results or 5)),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("Context vector query failed for collection '%s': %s", collection_name, exc)
            return []

        docs = (result or {}).get("documents") or []
        metas = (result or {}).get("metadatas") or []
        distances = (result or {}).get("distances") or []
        ids = (result or {}).get("ids") or []
        if not docs or not docs[0]:
            return []

        payload: List[Dict[str, Any]] = []
        for index, content in enumerate(docs[0]):
            metadata = metas[0][index] if metas and metas[0] and index < len(metas[0]) else {}
            distance = distances[0][index] if distances and distances[0] and index < len(distances[0]) else None
            row_id = ids[0][index] if ids and ids[0] and index < len(ids[0]) else None
            payload.append(
                {
                    "id": row_id,
                    "content": content,
                    "metadata": metadata or {},
                    "distance": distance,
                    "score": self.distance_to_score(distance),
                }
            )
        return payload

    def embed_text(self, text: str) -> List[float]:
        vector = [0.0] * self.dimensions
        for token in _tokenize(text):
            digest = hashlib.sha1(token.encode("utf-8")).hexdigest()
            bucket = int(digest[:8], 16) % self.dimensions
            sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [round(value / norm, 6) for value in vector]
        return vector

    def embed_texts(self, texts: Iterable[str]) -> List[List[float]]:
        return [self.embed_text(text) for text in texts]

    @staticmethod
    def distance_to_score(distance: Any) -> float:
        try:
            numeric = float(distance)
        except (TypeError, ValueError):
            return 0.0
        return round(max(0.0, min(1.0, 1.0 / (1.0 + numeric))), 4)


def _tokenize(text: str) -> List[str]:
    clean = "".join(ch.lower() if ch.isalnum() else " " for ch in str(text or ""))
    return [token for token in clean.split() if len(token) > 2]
