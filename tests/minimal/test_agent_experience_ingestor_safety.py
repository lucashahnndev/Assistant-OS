from __future__ import annotations

from types import SimpleNamespace

from services.context.ingestion.agent_experience_ingestor import AgentExperienceIngestor


class _FakeVectorStore:
    embedding_version = "test-emb-1"

    def __init__(self):
        self.documents = []

    def upsert_documents(self, collection_name, chunks):
        self.documents.extend(chunks)
        return len(chunks)

    def query(self, collection_name, query, n_results=3):
        return []


def _session(**overrides):
    base = {
        "session_id": "agent-exp-test",
        "decision_traces": [],
        "event_history": [],
        "task_registry": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_decision_trace_success_does_not_become_agent_experience():
    store = _FakeVectorStore()
    ingestor = AgentExperienceIngestor(vector_store=store)
    session = _session(
        decision_traces=[
            {
                "event_type": "COMPLETED",
                "decision_type": "EVENT_COORDINATION",
                "selected_outcome": "SUCCESS",
                "task_role": "Browser verification",
                "recovery_assessment": {"reason": "completed normally"},
            }
        ]
    )

    result = ingestor.promote_session_experience(session)

    assert result["accepted"] == 0
    assert store.documents == []


def test_failure_trace_can_still_become_agent_experience():
    store = _FakeVectorStore()
    ingestor = AgentExperienceIngestor(vector_store=store)
    session = _session(
        decision_traces=[
            {
                "event_type": "FAILED",
                "decision_type": "EVENT_COORDINATION",
                "selected_outcome": "RETRY",
                "task_role": "Browser verification",
                "recovery_assessment": {"reason": "timeout", "recommendation": "retry"},
            }
        ]
    )

    result = ingestor.promote_session_experience(session)

    assert result["accepted"] == 1
    assert len(store.documents) == 1


def test_negated_failure_language_is_not_promoted_as_experience():
    store = _FakeVectorStore()
    ingestor = AgentExperienceIngestor(vector_store=store)
    session = _session(
        event_history=[
            {
                "event_type": "FAILED",
                "failure_summary": "No failure was observed after the retry",
                "task_role": "Browser verification",
            }
        ]
    )

    result = ingestor.promote_session_experience(session)

    assert result["accepted"] == 0
    assert store.documents == []
