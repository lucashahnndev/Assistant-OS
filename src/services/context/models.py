from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ContextIntent(str, Enum):
    TASK_EXECUTION = "task_execution"
    CAPABILITY_LOOKUP = "capability_lookup"
    POLICY_LOOKUP = "policy_lookup"
    MEMORY_LOOKUP = "memory_lookup"
    TROUBLESHOOTING = "troubleshooting"
    CONVERSATIONAL = "conversational"
    GENERAL_KNOWLEDGE = "general_knowledge"


@dataclass(slots=True)
class RetrievalTarget:
    domain: str
    priority: int
    max_results: int = 3
    filters: Dict[str, Any] = field(default_factory=dict)
    active: bool = True
    notes: str = ""


@dataclass(slots=True)
class EvidenceItem:
    domain: str
    title: str
    content: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    timestamp: Optional[str] = None
    provenance: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ContextDiagnostics:
    intent: str
    selected_targets: List[str] = field(default_factory=list)
    evidence_domains: List[str] = field(default_factory=list)
    evidence_count: int = 0
    hint_present: bool = False
    hint_generated: bool = False
    hint_summary: List[str] = field(default_factory=list)
    hint_categories: List[str] = field(default_factory=list)
    hint_effects: List[str] = field(default_factory=list)
    hinted_domains: List[str] = field(default_factory=list)
    hint_applied: bool = False
    hint_ignored: bool = False
    hint_routing_changed: bool = False
    hint_ranking_changed: bool = False
    hint_low_signal: bool = False
    hint_impact_summary: List[str] = field(default_factory=list)
    queried_domains: Dict[str, bool] = field(default_factory=dict)
    result_counts_by_domain: Dict[str, int] = field(default_factory=dict)
    evidence_counts_by_domain: Dict[str, int] = field(default_factory=dict)
    evidence_counts_by_domain_suppressed: Dict[str, int] = field(default_factory=dict)
    evidence_counts_by_domain_selected: Dict[str, int] = field(default_factory=dict)
    rerank_win_by_domain: Dict[str, int] = field(default_factory=dict)
    domain_conflict_resolution_summary: List[str] = field(default_factory=list)
    total_evidence_chars: int = 0
    evidence_density_reduction_count: int = 0
    low_value_suppressed_count: int = 0
    ingestion_stats_by_domain: Dict[str, Dict[str, int]] = field(default_factory=dict)
    rerank_summary: List[str] = field(default_factory=list)
    classifier_notes: List[str] = field(default_factory=list)
    retrieval_notes: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ContextBundle:
    situational_context: Dict[str, Any] = field(default_factory=dict)
    session_context: Dict[str, Any] = field(default_factory=dict)
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    diagnostics: ContextDiagnostics = field(
        default_factory=lambda: ContextDiagnostics(intent=ContextIntent.CONVERSATIONAL.value)
    )


@dataclass(slots=True)
class RAGChunkMetadata:
    doc_type: str
    collection_type: str
    source_file: str
    created_at: str
    updated_at: str
    embedding_version: str
    capability_id: str = ""
    action_id: str = ""
    principal_id: str = ""
    tenant_id: str = ""
    trust_level: str = ""
    source_type: str = ""
    title: str = ""
    chunk_index: int = 0
    total_chunks: int = 1
    procedure_id: str = ""
    example_type: str = ""
    step_index: int = 0
    section: str = ""
    tags: str = ""
    success_signal: str = ""
    policy_id: str = ""
    policy_visibility: str = ""
    rule_group: str = ""
    scope_hint: str = ""
    status: str = ""
    experience_type: str = ""
    environment_hint: str = ""
    provenance_hash: str = ""
    session_id: str = ""
    error_type: str = ""
    recovery_type: str = ""
    knowledge_scope: str = ""
    origin: str = ""
    author: str = ""
    version: str = ""

    def to_chroma(self) -> Dict[str, Any]:
        payload = {
            "doc_type": self.doc_type,
            "collection_type": self.collection_type,
            "source_file": self.source_file,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "embedding_version": self.embedding_version,
            "capability_id": self.capability_id,
            "action_id": self.action_id,
            "principal_id": self.principal_id,
            "tenant_id": self.tenant_id,
            "trust_level": self.trust_level,
            "source_type": self.source_type,
            "title": self.title,
            "chunk_index": int(self.chunk_index),
            "total_chunks": int(self.total_chunks),
            "procedure_id": self.procedure_id,
            "example_type": self.example_type,
            "step_index": int(self.step_index),
            "section": self.section,
            "tags": self.tags,
            "success_signal": self.success_signal,
            "policy_id": self.policy_id,
            "policy_visibility": self.policy_visibility,
            "rule_group": self.rule_group,
            "scope_hint": self.scope_hint,
            "status": self.status,
            "experience_type": self.experience_type,
            "environment_hint": self.environment_hint,
            "provenance_hash": self.provenance_hash,
            "session_id": self.session_id,
            "error_type": self.error_type,
            "recovery_type": self.recovery_type,
            "knowledge_scope": self.knowledge_scope,
            "origin": self.origin,
            "author": self.author,
            "version": self.version,
        }
        return {key: value for key, value in payload.items() if value not in (None, "")}


@dataclass(slots=True)
class RAGChunk:
    chunk_id: str
    content: str
    metadata: RAGChunkMetadata
