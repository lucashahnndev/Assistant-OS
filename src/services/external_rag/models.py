from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class ExecutionBudgets:
    latency_budget_ms: int = 12000
    cost_budget: float = 0.0
    max_providers: int = 2
    max_fallback_depth: int = 2
    max_parallelism: int = 1
    max_retries: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "latency_budget_ms": int(max(500, self.latency_budget_ms)),
            "cost_budget": float(max(0.0, self.cost_budget)),
            "max_providers": int(max(1, self.max_providers)),
            "max_fallback_depth": int(max(1, self.max_fallback_depth)),
            "max_parallelism": int(max(1, self.max_parallelism)),
            "max_retries": int(max(0, self.max_retries)),
        }


@dataclass(slots=True)
class PlanStep:
    step_id: str
    query: str
    intent: str
    subintent: str
    constraints: Dict[str, Any] = field(default_factory=dict)
    selected_providers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "query": self.query,
            "intent": self.intent,
            "subintent": self.subintent,
            "constraints": dict(self.constraints),
            "selected_providers": list(self.selected_providers),
        }


@dataclass(slots=True)
class RetrievalPlan:
    query_id: str
    intent: str
    subintent: str
    constraints: Dict[str, Any] = field(default_factory=dict)
    plan_steps: List[PlanStep] = field(default_factory=list)
    selected_providers: List[str] = field(default_factory=list)
    merge_strategy: str = "synthesize_with_citations"
    fallback_chain: List[str] = field(default_factory=list)
    budgets: ExecutionBudgets = field(default_factory=ExecutionBudgets)
    provider_runtime_scorecard: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    explanation_trace: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "intent": self.intent,
            "subintent": self.subintent,
            "constraints": dict(self.constraints),
            "plan_steps": [step.to_dict() for step in self.plan_steps],
            "selected_providers": list(self.selected_providers),
            "merge_strategy": self.merge_strategy,
            "fallback_chain": list(self.fallback_chain),
            "budgets": self.budgets.to_dict(),
            "provider_runtime_scorecard": dict(self.provider_runtime_scorecard),
            "explanation_trace": list(self.explanation_trace),
        }


@dataclass(slots=True)
class EvidenceItem:
    provider: str
    source_url: str
    source_title: str
    quote: str
    chunk_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "quote": self.quote,
            "chunk_id": self.chunk_id,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class RoutingDecision:
    provider: str
    used: bool
    reason: str
    score: float
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "used": bool(self.used),
            "reason": self.reason,
            "score": float(self.score),
            "score_breakdown": dict(self.score_breakdown),
        }


@dataclass(slots=True)
class RetrievalRunResult:
    answer_md: str
    status: str
    sources: List[Dict[str, Any]]
    evidence: List[EvidenceItem]
    stats: Dict[str, Any]
    traces: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "answer_md": self.answer_md,
            "sources": list(self.sources),
            "evidence": [item.to_dict() for item in self.evidence],
            "stats": dict(self.stats),
            "traces": dict(self.traces),
            "warnings": list(self.warnings),
        }
