from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from .models import ContextIntent, EvidenceItem


@dataclass(slots=True)
class RankedEvidence:
    item: EvidenceItem
    final_score: float
    factors: Dict[str, float]


class ContextReranker:
    """Deterministic cross-domain reranker for broker evidence."""

    _TRUST_WEIGHTS = {
        "system": 1.0,
        "curated": 0.92,
        "user": 0.76,
        "imported": 0.66,
        "low-confidence": 0.36,
        "high": 1.0,
        "medium": 0.72,
        "low": 0.45,
        "": 0.6,
    }
    _POLICY_VISIBILITY_WEIGHTS = {
        "public": 1.0,
        "tenant": 0.94,
        "principal": 0.9,
        "planner": 0.96,
        "internal": 0.82,
        "restricted": 0.55,
        "": 0.8,
    }
    _KNOWLEDGE_SCOPE_WEIGHTS = {
        "global": 1.0,
        "workspace": 0.9,
        "tenant": 0.92,
        "principal": 0.88,
        "": 0.84,
    }
    _INTENT_DOMAIN_BONUS = {
        ContextIntent.POLICY_LOOKUP.value: {"policies": 0.35, "procedures": 0.08, "capability_knowledge": 0.05},
        ContextIntent.TASK_EXECUTION.value: {"procedures": 0.26, "capability_knowledge": 0.18, "user_memory": 0.1, "agent_experience": 0.04, "custom_knowledge": 0.12, "external_knowledge": 0.03, "policies": 0.04},
        ContextIntent.TROUBLESHOOTING.value: {"agent_experience": 0.3, "procedures": 0.22, "examples": 0.12, "capability_knowledge": 0.12, "user_memory": 0.08, "external_knowledge": 0.04, "custom_knowledge": 0.05, "policies": 0.04},
        ContextIntent.CAPABILITY_LOOKUP.value: {"capability_knowledge": 0.26, "examples": 0.14, "external_knowledge": 0.08, "policies": 0.06},
        ContextIntent.MEMORY_LOOKUP.value: {"user_memory": 0.28},
        ContextIntent.GENERAL_KNOWLEDGE.value: {"external_knowledge": 0.24, "custom_knowledge": 0.3},
    }
    _DOMAIN_CAPS = {
        "agent_experience": 1,
        "custom_knowledge": 1,
        "external_knowledge": 1,
        "policies": 1,
        "examples": 1,
        "procedures": 2,
        "capability_knowledge": 2,
        "user_memory": 2,
    }

    def rank(
        self,
        *,
        evidence_items: List[EvidenceItem],
        priorities: Dict[str, int],
        intent: str,
        broker_hints: Dict[str, object] | None = None,
        max_items: int = 6,
    ) -> Tuple[List[EvidenceItem], List[str]]:
        ranked = [self._score_item(item=item, priorities=priorities, intent=intent, broker_hints=broker_hints) for item in evidence_items]
        ranked.sort(key=lambda row: (-row.final_score, priorities.get(row.item.domain, 99), row.item.title))

        selected: List[EvidenceItem] = []
        traces: List[str] = []
        per_domain_count: Dict[str, int] = {}
        for row in ranked:
            domain = row.item.domain
            if per_domain_count.get(domain, 0) >= self._domain_cap(domain=domain, intent=intent):
                continue
            selected.append(row.item)
            per_domain_count[domain] = per_domain_count.get(domain, 0) + 1
            traces.append(
                f"{domain}:{row.item.title}:final={row.final_score:.3f}:"
                f"priority={row.factors['priority']:.2f},retrieval={row.factors['retrieval']:.2f},"
                f"trust={row.factors['trust']:.2f},freshness={row.factors['freshness']:.2f},"
                f"intent={row.factors['intent']:.2f},hint={row.factors['hint']:.2f},balance={row.factors['balance']:.2f},"
                f"visibility={row.factors['visibility']:.2f},scope={row.factors['scope']:.2f}"
            )
            if len(selected) >= max(1, int(max_items or 1)):
                break
        return selected, traces

    def _score_item(self, *, item: EvidenceItem, priorities: Dict[str, int], intent: str, broker_hints: Dict[str, object] | None = None) -> RankedEvidence:
        priority_factor = self._priority_factor(priorities.get(item.domain, 99))
        retrieval_factor = max(0.0, min(1.0, float(item.score or 0.0)))
        trust_factor = self._trust_factor(item.metadata)
        freshness_factor = self._freshness_factor(item.timestamp or item.metadata.get("updated_at") if isinstance(item.metadata, dict) else None)
        intent_factor = self._intent_factor(domain=item.domain, intent=intent)
        hint_factor = self._hint_factor(domain=item.domain, broker_hints=broker_hints)
        balance_factor = self._balance_factor(domain=item.domain, intent=intent, metadata=item.metadata, broker_hints=broker_hints)
        visibility_factor = self._visibility_factor(item.metadata)
        scope_factor = self._scope_factor(item.metadata)
        final_score = round(
            (priority_factor * 0.22)
            + (retrieval_factor * 0.3)
            + (trust_factor * 0.16)
            + (freshness_factor * 0.08)
            + (intent_factor * 0.12)
            + (hint_factor * 0.04)
            + (balance_factor * 0.06)
            + (visibility_factor * 0.05)
            + (scope_factor * 0.05),
            4,
        )
        return RankedEvidence(
            item=item,
            final_score=final_score,
            factors={
                "priority": priority_factor,
                "retrieval": retrieval_factor,
                "trust": trust_factor,
                "freshness": freshness_factor,
                "intent": intent_factor,
                "hint": hint_factor,
                "balance": balance_factor,
                "visibility": visibility_factor,
                "scope": scope_factor,
            },
        )

    @staticmethod
    def _priority_factor(priority: int) -> float:
        bounded = max(1, min(int(priority or 99), 8))
        return round(1.0 / bounded, 4)

    def _trust_factor(self, metadata: Dict[str, object]) -> float:
        trust_level = str((metadata or {}).get("trust_level") or "").strip().lower()
        return self._TRUST_WEIGHTS.get(trust_level, 0.6)

    @staticmethod
    def _freshness_factor(timestamp: object) -> float:
        text = str(timestamp or "").strip()
        if not text:
            return 0.5
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return 0.5
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 86400.0)
        if age_days <= 7:
            return 1.0
        if age_days <= 30:
            return 0.82
        if age_days <= 180:
            return 0.64
        return 0.45

    def _intent_factor(self, *, domain: str, intent: str) -> float:
        bonus = self._INTENT_DOMAIN_BONUS.get(intent, {}).get(domain, 0.02)
        return round(min(1.0, 0.45 + bonus), 4)

    def _visibility_factor(self, metadata: Dict[str, object]) -> float:
        visibility = str((metadata or {}).get("policy_visibility") or "").strip().lower()
        return self._POLICY_VISIBILITY_WEIGHTS.get(visibility, 0.8)

    def _scope_factor(self, metadata: Dict[str, object]) -> float:
        scope = str((metadata or {}).get("knowledge_scope") or "").strip().lower()
        return self._KNOWLEDGE_SCOPE_WEIGHTS.get(scope, 0.84)

    def _balance_factor(
        self,
        *,
        domain: str,
        intent: str,
        metadata: Dict[str, object],
        broker_hints: Dict[str, object] | None,
    ) -> float:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        scope = str((metadata or {}).get("knowledge_scope") or "").strip().lower()
        boost = 0.5
        if intent == ContextIntent.TASK_EXECUTION.value:
            if domain in {"procedures", "capability_knowledge"}:
                boost += 0.18
            if domain == "custom_knowledge":
                boost += 0.12
            if domain == "examples":
                boost -= 0.08
            if domain == "policies" and not bool(hints.get("approval_pending")):
                boost -= 0.08
        elif intent == ContextIntent.TROUBLESHOOTING.value:
            if domain == "agent_experience" and bool(hints.get("troubleshooting_active")):
                boost += 0.22
            if domain == "procedures":
                boost += 0.14
            if domain == "examples":
                boost -= 0.04
        elif intent == ContextIntent.CAPABILITY_LOOKUP.value:
            if domain == "capability_knowledge":
                boost += 0.18
            if domain == "examples":
                boost += 0.06
            if domain == "policies":
                boost -= 0.06
        elif intent == ContextIntent.POLICY_LOOKUP.value:
            if domain == "policies":
                boost += 0.2
            if domain == "procedures":
                boost += 0.04
        elif intent == ContextIntent.GENERAL_KNOWLEDGE.value:
            if domain == "custom_knowledge" and scope in {"workspace", "tenant", "principal"}:
                boost += 0.16
            if domain == "external_knowledge":
                boost -= 0.02
        return round(min(1.0, max(0.1, boost)), 4)

    @staticmethod
    def _hint_factor(*, domain: str, broker_hints: Dict[str, object] | None) -> float:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        boost = 0.45
        if domain == "agent_experience" and bool(hints.get("troubleshooting_active")):
            boost += 0.18
        if domain == "policies" and bool(hints.get("approval_pending")):
            boost += 0.18
        if domain == "capability_knowledge" and str(hints.get("hot_action_namespace") or "").strip():
            boost += 0.12
        if domain == "procedures" and str(hints.get("primary_task_id") or "").strip():
            boost += 0.1
        if domain in {"procedures", "agent_experience"} and bool(hints.get("blocker_active")):
            boost += 0.08
        return round(min(1.0, boost), 4)

    def _domain_cap(self, *, domain: str, intent: str) -> int:
        if intent == ContextIntent.TROUBLESHOOTING.value:
            if domain == "agent_experience":
                return 2
            if domain in {"procedures", "capability_knowledge"}:
                return 2
        if intent == ContextIntent.TASK_EXECUTION.value and domain in {"procedures", "capability_knowledge"}:
            return 2
        if intent == ContextIntent.CAPABILITY_LOOKUP.value and domain == "capability_knowledge":
            return 3
        if intent == ContextIntent.POLICY_LOOKUP.value and domain == "policies":
            return 2
        if intent == ContextIntent.GENERAL_KNOWLEDGE.value and domain in {"external_knowledge", "custom_knowledge"}:
            return 2
        return self._DOMAIN_CAPS.get(domain, 2)
