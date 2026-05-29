from __future__ import annotations

from unittest.mock import MagicMock

from core.orchestrator import AgentOrchestrator
from core.session import Session
from services.context.ingestion.user_memory_ingestor import UserMemoryIngestor


class _FakeVectorStore:
    embedding_version = "test-emb-1"

    def __init__(self):
        self.calls = []

    def upsert_documents(self, collection_name, chunks):
        self.calls.append((collection_name, chunks))
        return len(chunks)


def test_user_memory_ingestor_promotes_only_accepted_entries():
    vector_store = _FakeVectorStore()
    ingestor = UserMemoryIngestor(vector_store=vector_store)
    session = Session("test-session")
    session.memory = [
        {
            "memory_id": "m1",
            "content": "accepted fact",
            "memory_type": "fact",
            "status": "accepted",
            "confidence": 0.9,
        },
        {
            "memory_id": "m2",
            "content": "candidate fact",
            "memory_type": "fact",
            "status": "candidate",
            "confidence": 0.9,
        },
        {
            "memory_id": "m3",
            "content": "rejected fact",
            "memory_type": "fact",
            "status": "rejected",
            "confidence": 0.9,
        },
    ]

    result = ingestor.promote_session_memory(session, principal_id="user-1", tenant_id="tenant-1")

    assert result["promoted"] == 1
    assert len(vector_store.calls) == 1
    collection_name, chunks = vector_store.calls[0]
    assert collection_name == "user_memory"
    assert len(chunks) == 1
    assert "accepted fact" in chunks[0].content


def test_orchestrator_retrieval_filters_non_accepted_memory():
    orchestrator = AgentOrchestrator(MagicMock())
    session = Session("test-session")
    session.history = [{"role": "user", "content": "Please remember this later."}]
    session.memory = [
        {
            "memory_id": "accepted",
            "content": "Keep this memory",
            "memory_type": "fact",
            "status": "accepted",
            "confidence": 0.9,
        },
        {
            "memory_id": "candidate",
            "content": "Do not surface this",
            "memory_type": "fact",
            "status": "candidate",
            "confidence": 0.9,
        },
    ]

    memory = orchestrator._retrieve_relevant_memory(session, "Do you remember?")

    assert len(memory) == 1
    assert memory[0]["memory_id"] == "accepted"
