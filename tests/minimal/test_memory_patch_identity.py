from __future__ import annotations

from core.session import Session
from services.context.ingestion.user_memory_ingestor import UserMemoryIngestor


class _FakeVectorStore:
    embedding_version = "test-emb-1"

    def upsert_documents(self, collection_name, chunks):
        return len(chunks)


def test_session_apply_memory_patch_matches_memory_id():
    session = Session("test-session")
    session.memory = [
        {
            "memory_id": "mem-1",
            "content": "original",
            "memory_type": "fact",
            "status": "accepted",
        }
    ]

    assert session.apply_memory_patch("mem-1", {"content": "patched"}, "admin", "fix")
    assert session.memory[0]["content"] == "patched"


def test_user_memory_chunk_id_uses_memory_id_when_present():
    ingestor = UserMemoryIngestor(vector_store=_FakeVectorStore())
    entry_one = {
        "memory_id": "mem-1",
        "content": "first version",
        "memory_type": "fact",
        "status": "accepted",
        "confidence": 0.9,
    }
    entry_two = {
        "memory_id": "mem-1",
        "content": "updated version",
        "memory_type": "fact",
        "status": "accepted",
        "confidence": 0.9,
    }

    chunk_one = ingestor._chunk_from_entry(entry=entry_one, principal_id="u", tenant_id="t")
    chunk_two = ingestor._chunk_from_entry(entry=entry_two, principal_id="u", tenant_id="t")

    assert chunk_one.chunk_id == chunk_two.chunk_id
