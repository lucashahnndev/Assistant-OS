from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from utils.logging_config import get_logger

from services.memory.episodic_memory import EpisodicMemoryService

from .ingestion import (
    AgentExperienceIngestor,
    CapabilityKnowledgeIngestor,
    CustomKnowledgeIngestor,
    ExampleIngestor,
    ExternalKnowledgeIngestor,
    PolicyIngestor,
    ProcedureIngestor,
    UserMemoryIngestor,
)
from .retrieval import (
    AgentExperienceRetriever,
    CapabilityKnowledgeRetriever,
    CustomKnowledgeRetriever,
    ExampleRetriever,
    ExternalKnowledgeRetriever,
    PolicyRetriever,
    ProcedureRetriever,
    UserMemoryRetriever,
)
from .evidence_builder import EvidenceBuilder
from .intent_classifier import IntentClassifier
from .models import ContextBundle, ContextDiagnostics, ContextIntent, RetrievalTarget
from .reranker import ContextReranker
from .retrieval_router import RetrievalRouter
from .vector_store import ContextVectorStore

logger = get_logger("ContextBroker")


class ContextBroker:
    """Phase 2A broker that classifies, routes, retrieves, reranks, and normalizes context evidence."""

    def __init__(
        self,
        *,
        intent_classifier: Optional[IntentClassifier] = None,
        retrieval_router: Optional[RetrievalRouter] = None,
        evidence_builder: Optional[EvidenceBuilder] = None,
        reranker: Optional[ContextReranker] = None,
        retrieval_handlers: Optional[Dict[str, Callable[..., List[Dict[str, Any]]]]] = None,
    ):
        self.intent_classifier = intent_classifier or IntentClassifier()
        self.retrieval_router = retrieval_router or RetrievalRouter()
        self.evidence_builder = evidence_builder or EvidenceBuilder()
        self.reranker = reranker or ContextReranker()
        self.retrieval_handlers = retrieval_handlers or self.default_handlers()

    def build_bundle(
        self,
        *,
        user_input: str,
        session,
        capability_registry=None,
        allowed_actions: Optional[List[str]] = None,
        situational_context: Optional[Dict[str, Any]] = None,
        session_context: Optional[Dict[str, Any]] = None,
        broker_hints: Optional[Dict[str, Any]] = None,
    ) -> ContextBundle:
        intent, classifier_notes = self.intent_classifier.classify(user_input, session=session)
        baseline_targets = self.retrieval_router.route(intent, user_input=user_input, broker_hints=None) if broker_hints else []
        targets = self.retrieval_router.route(intent, user_input=user_input, broker_hints=broker_hints)
        evidence_items = []
        retrieval_notes: List[str] = []
        priorities = {target.domain: target.priority for target in targets}
        result_counts_by_domain: Dict[str, int] = {}
        evidence_counts_by_domain: Dict[str, int] = {}
        ingestion_stats_by_domain: Dict[str, Dict[str, int]] = {}
        queried_domains = {target.domain: bool(target.active) for target in targets}
        baseline_by_domain = {target.domain: target for target in baseline_targets}
        hinted_domains: List[str] = []
        hint_effects: List[str] = []
        hint_impact_summary: List[str] = []

        for target in targets:
            baseline_target = baseline_by_domain.get(target.domain)
            if baseline_target is None:
                continue
            if bool(target.active) != bool(baseline_target.active):
                hinted_domains.append(target.domain)
                hint_effects.append(f"{target.domain}:active")
                hint_impact_summary.append(f"{target.domain}:active")
            if int(target.priority) != int(baseline_target.priority):
                hinted_domains.append(target.domain)
                hint_effects.append(f"{target.domain}:priority:{baseline_target.priority}->{target.priority}")
                hint_impact_summary.append(f"{target.domain}:priority")

        for target in targets:
            if not target.active:
                retrieval_notes.append(f"{target.domain}:inactive:{target.notes or 'stub'}")
                result_counts_by_domain[target.domain] = 0
                evidence_counts_by_domain[target.domain] = 0
                continue
            handler = self.retrieval_handlers.get(target.domain)
            if handler is None:
                retrieval_notes.append(f"{target.domain}:unhandled")
                result_counts_by_domain[target.domain] = 0
                evidence_counts_by_domain[target.domain] = 0
                continue

            started = time.time()
            try:
                raw_items = handler(
                    query=user_input,
                    session=session,
                    capability_registry=capability_registry,
                    allowed_actions=allowed_actions,
                    target=target,
                )
            except Exception as exc:
                logger.warning("Context broker retrieval failed for domain '%s': %s", target.domain, exc)
                retrieval_notes.append(f"{target.domain}:error:{exc}")
                result_counts_by_domain[target.domain] = 0
                evidence_counts_by_domain[target.domain] = 0
                continue
            stats = getattr(getattr(handler, "__self__", None), "last_ingestion_stats", None)
            if isinstance(stats, dict) and stats:
                ingestion_stats_by_domain[target.domain] = {
                    str(key): int(value) for key, value in stats.items() if isinstance(value, (int, float))
                }

            result_counts_by_domain[target.domain] = len(raw_items[: target.max_results])
            built = self.evidence_builder.build(target.domain, raw_items[: target.max_results])
            evidence_items.extend(built[: target.max_results])
            evidence_counts_by_domain[target.domain] = len(built[: target.max_results])
            retrieval_notes.append(
                f"{target.domain}:items={len(built[: target.max_results])}:ms={int((time.time() - started) * 1000)}"
            )

        max_items = self._max_evidence_items(intent=intent.value)
        evidence_items, rerank_summary = self.reranker.rank(
            evidence_items=evidence_items,
            priorities=priorities,
            intent=intent.value,
            broker_hints=broker_hints,
            max_items=max_items,
        )
        baseline_rerank_summary: List[str] = []
        baseline_ranked_items = []
        if broker_hints and evidence_items:
            baseline_priorities = {target.domain: target.priority for target in baseline_targets}
            baseline_ranked_items, baseline_rerank_summary = self.reranker.rank(
                evidence_items=evidence_items,
                priorities=baseline_priorities,
                intent=intent.value,
                broker_hints=None,
                max_items=6,
            )
        hint_summary = [
            str(item).strip()
            for item in list((broker_hints or {}).get("hint_summary") or [])
            if str(item).strip()
        ][:6]
        hint_categories = [
            str(item).strip()
            for item in list((broker_hints or {}).get("hint_categories") or [])
            if str(item).strip()
        ][:6]
        hint_note_effects = [
            f"{target.domain}:{target.notes}"
            for target in targets
            if "hint:" in str(target.notes or "")
        ][:8]
        hint_effects.extend(hint_note_effects)
        ranking_changed_by_hint = False
        if broker_hints:
            ranked_signature = [(item.domain, item.title) for item in evidence_items]
            baseline_signature = [(item.domain, item.title) for item in baseline_ranked_items]
            ranking_changed_by_hint = ranked_signature != baseline_signature
            if ranking_changed_by_hint:
                for index, pair in enumerate(ranked_signature[:6]):
                    if index >= len(baseline_signature) or pair != baseline_signature[index]:
                        domain = str(pair[0] or "")
                        if domain:
                            hinted_domains.append(domain)
                            hint_impact_summary.append(f"{domain}:rank")
                if not hint_impact_summary:
                    hint_impact_summary.append("ranking:changed")
        hint_effects = list(dict.fromkeys(hint_effects))[:8]
        hinted_domains = list(dict.fromkeys(str(item).strip() for item in hinted_domains if str(item).strip()))[:8]
        hint_impact_summary = list(dict.fromkeys(str(item).strip() for item in hint_impact_summary if str(item).strip()))[:8]
        hint_applied = bool(hint_impact_summary)
        hint_ignored = bool(broker_hints) and not hint_applied
        tuned_items, tuning_stats = self._apply_evidence_tuning(
            evidence_items=evidence_items,
            intent=intent.value,
            priorities=priorities,
            broker_hints=broker_hints,
        )
        evidence_items = tuned_items
        evidence_counts_by_domain = {}
        for item in evidence_items:
            evidence_counts_by_domain[item.domain] = evidence_counts_by_domain.get(item.domain, 0) + 1
        evidence_domains = sorted({item.domain for item in evidence_items})
        diagnostics = ContextDiagnostics(
            intent=intent.value,
            selected_targets=[target.domain for target in targets],
            evidence_domains=evidence_domains,
            evidence_count=len(evidence_items),
            hint_present=bool(broker_hints),
            hint_generated=bool(broker_hints),
            hint_summary=hint_summary,
            hint_categories=hint_categories,
            hint_effects=hint_effects,
            hinted_domains=hinted_domains,
            hint_applied=hint_applied,
            hint_ignored=hint_ignored,
            hint_routing_changed=any(item.endswith(":active") or item.endswith(":priority") for item in hint_impact_summary),
            hint_ranking_changed=ranking_changed_by_hint,
            hint_low_signal=str((broker_hints or {}).get("signal_strength") or "none") in {"none", "low"},
            hint_impact_summary=hint_impact_summary,
            queried_domains=queried_domains,
            result_counts_by_domain=result_counts_by_domain,
            evidence_counts_by_domain=evidence_counts_by_domain,
            evidence_counts_by_domain_selected=tuning_stats.get("selected_by_domain", {}),
            evidence_counts_by_domain_suppressed=tuning_stats.get("suppressed_by_domain", {}),
            rerank_win_by_domain=tuning_stats.get("rerank_win_by_domain", {}),
            domain_conflict_resolution_summary=tuning_stats.get("conflict_summary", []),
            total_evidence_chars=tuning_stats.get("total_evidence_chars", 0),
            evidence_density_reduction_count=tuning_stats.get("density_reduction_count", 0),
            low_value_suppressed_count=tuning_stats.get("low_value_suppressed_count", 0),
            ingestion_stats_by_domain=ingestion_stats_by_domain,
            rerank_summary=(rerank_summary[:6] + ([f"baseline:{item}" for item in baseline_rerank_summary[:2]] if baseline_rerank_summary else []))[:8],
            classifier_notes=classifier_notes,
            retrieval_notes=retrieval_notes,
        )
        bundle = ContextBundle(
            situational_context=situational_context or {},
            session_context=session_context or {},
            evidence_items=evidence_items,
            diagnostics=diagnostics,
        )
        logger.info(
            "ContextBroker | session=%s intent=%s targets=%s evidence_domains=%s evidence_count=%d",
            getattr(session, "session_id", "unknown"),
            diagnostics.intent,
            ",".join(diagnostics.selected_targets) or "-",
            ",".join(diagnostics.evidence_domains) or "-",
            diagnostics.evidence_count,
        )
        return bundle

    @staticmethod
    def _max_evidence_items(*, intent: str) -> int:
        if intent == ContextIntent.TROUBLESHOOTING.value:
            return 5
        if intent == ContextIntent.TASK_EXECUTION.value:
            return 5
        if intent == ContextIntent.CAPABILITY_LOOKUP.value:
            return 4
        if intent == ContextIntent.POLICY_LOOKUP.value:
            return 3
        if intent == ContextIntent.MEMORY_LOOKUP.value:
            return 2
        if intent == ContextIntent.CONVERSATIONAL.value:
            return 2
        return 4

    def _apply_evidence_tuning(
        self,
        *,
        evidence_items: List[Any],
        intent: str,
        priorities: Dict[str, int],
        broker_hints: Optional[Dict[str, Any]],
    ) -> tuple[List[Any], Dict[str, Any]]:
        kept: List[Any] = []
        suppressed_by_domain: Dict[str, int] = {}
        selected_by_domain: Dict[str, int] = {}
        rerank_win_by_domain: Dict[str, int] = {}
        conflict_summary: List[str] = []
        seen_fingerprints = set()
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        total_chars = 0
        density_reduced = 0
        low_value_suppressed = 0

        def _fingerprint(item: Any) -> str:
            text = f"{getattr(item, 'title', '')} {getattr(item, 'content', '')}".lower()
            return " ".join("".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text).split())

        def _suppress(item: Any, reason: str) -> None:
            domain = getattr(item, "domain", "unknown")
            suppressed_by_domain[domain] = suppressed_by_domain.get(domain, 0) + 1
            if reason:
                conflict_summary.append(reason)

        for index, item in enumerate(evidence_items):
            domain = getattr(item, "domain", "")
            if not domain:
                _suppress(item, "")
                continue

            fingerprint = _fingerprint(item)
            if fingerprint in seen_fingerprints:
                density_reduced += 1
                _suppress(item, f"duplicate:{domain}")
                continue

            if intent != ContextIntent.POLICY_LOOKUP.value and domain == "policies" and not bool(hints.get("approval_pending")):
                low_value_suppressed += 1
                _suppress(item, "policies:suppressed")
                continue

            if intent in {ContextIntent.TASK_EXECUTION.value, ContextIntent.TROUBLESHOOTING.value}:
                if domain == "examples" and any(k.domain == "procedures" for k in kept) and selected_by_domain.get("examples", 0) >= 1:
                    low_value_suppressed += 1
                    _suppress(item, "examples:suppressed:procedures_present")
                    continue
                if intent == ContextIntent.TASK_EXECUTION.value and domain == "agent_experience" and not bool(hints.get("troubleshooting_active")):
                    low_value_suppressed += 1
                    _suppress(item, "agent_experience:suppressed:no_troubleshooting")
                    continue

            if intent == ContextIntent.CAPABILITY_LOOKUP.value and domain == "examples":
                if selected_by_domain.get("capability_knowledge", 0) >= 2:
                    low_value_suppressed += 1
                    _suppress(item, "examples:suppressed:capability_present")
                    continue

            if domain == "external_knowledge" and any(k.domain == "custom_knowledge" for k in kept):
                if intent != ContextIntent.GENERAL_KNOWLEDGE.value:
                    low_value_suppressed += 1
                    _suppress(item, "external:suppressed:custom_present")
                    continue
                trust = str(getattr(item, "metadata", {}).get("trust_level") or "").lower()
                if trust not in {"system", "curated", "high"}:
                    low_value_suppressed += 1
                    _suppress(item, "external:suppressed:custom_focus")
                    continue

            if domain == "custom_knowledge":
                if any(k.domain == "external_knowledge" for k in kept):
                    if intent != ContextIntent.GENERAL_KNOWLEDGE.value:
                        low_value_suppressed += 1
                        kept = [k for k in kept if k.domain != "external_knowledge"]
                        if selected_by_domain.get("external_knowledge", 0) > 0:
                            selected_by_domain["external_knowledge"] = selected_by_domain.get("external_knowledge", 0) - 1
                        suppressed_by_domain["external_knowledge"] = suppressed_by_domain.get("external_knowledge", 0) + 1
                        conflict_summary.append("external:suppressed:custom_present")
                    else:
                        external_items = [k for k in kept if k.domain == "external_knowledge"]
                        external_trust = ""
                        if external_items:
                            external_trust = str(getattr(external_items[0], "metadata", {}).get("trust_level") or "").lower()
                        if external_trust not in {"system", "curated", "high"}:
                            low_value_suppressed += 1
                            kept = [k for k in kept if k.domain != "external_knowledge"]
                            if selected_by_domain.get("external_knowledge", 0) > 0:
                                selected_by_domain["external_knowledge"] = selected_by_domain.get("external_knowledge", 0) - 1
                            suppressed_by_domain["external_knowledge"] = suppressed_by_domain.get("external_knowledge", 0) + 1
                            conflict_summary.append("external:suppressed:custom_focus")

            per_domain_cap = 2 if domain in {"procedures", "capability_knowledge"} else 1
            if intent == ContextIntent.TROUBLESHOOTING.value and domain == "agent_experience" and bool(hints.get("troubleshooting_active")):
                per_domain_cap = 2
            if selected_by_domain.get(domain, 0) >= per_domain_cap:
                density_reduced += 1
                _suppress(item, f"cap:{domain}")
                continue

            kept.append(item)
            selected_by_domain[domain] = selected_by_domain.get(domain, 0) + 1
            seen_fingerprints.add(fingerprint)
            total_chars += len(getattr(item, "content", "") or "")
            if index < 2:
                rerank_win_by_domain[domain] = rerank_win_by_domain.get(domain, 0) + 1

        conflict_summary = list(dict.fromkeys([entry for entry in conflict_summary if entry]))[:8]
        return kept, {
            "suppressed_by_domain": suppressed_by_domain,
            "selected_by_domain": selected_by_domain,
            "rerank_win_by_domain": rerank_win_by_domain,
            "conflict_summary": conflict_summary,
            "total_evidence_chars": total_chars,
            "density_reduction_count": density_reduced,
            "low_value_suppressed_count": low_value_suppressed,
        }

    @staticmethod
    def default_handlers() -> Dict[str, Callable[..., List[Dict[str, Any]]]]:
        try:
            vector_store = ContextVectorStore()
            capability_ingestor = CapabilityKnowledgeIngestor(vector_store=vector_store)
            procedure_ingestor = ProcedureIngestor(vector_store=vector_store)
            example_ingestor = ExampleIngestor(vector_store=vector_store)
            policy_ingestor = PolicyIngestor(vector_store=vector_store)
            user_memory_ingestor = UserMemoryIngestor(vector_store=vector_store)
            external_knowledge_ingestor = ExternalKnowledgeIngestor(vector_store=vector_store)
            custom_knowledge_ingestor = CustomKnowledgeIngestor(vector_store=vector_store)
            agent_experience_ingestor = AgentExperienceIngestor(
                vector_store=vector_store,
                episodic_memory_service=EpisodicMemoryService(),
            )
            capability_retriever = CapabilityKnowledgeRetriever(vector_store=vector_store, ingestor=capability_ingestor)
            procedure_retriever = ProcedureRetriever(vector_store=vector_store, ingestor=procedure_ingestor)
            example_retriever = ExampleRetriever(vector_store=vector_store, ingestor=example_ingestor)
            policy_retriever = PolicyRetriever(vector_store=vector_store, ingestor=policy_ingestor)
            user_memory_retriever = UserMemoryRetriever(vector_store=vector_store, ingestor=user_memory_ingestor)
            external_knowledge_retriever = ExternalKnowledgeRetriever(
                vector_store=vector_store,
                ingestor=external_knowledge_ingestor,
            )
            custom_knowledge_retriever = CustomKnowledgeRetriever(
                vector_store=vector_store,
                ingestor=custom_knowledge_ingestor,
            )
            agent_experience_retriever = AgentExperienceRetriever(
                vector_store=vector_store,
                ingestor=agent_experience_ingestor,
            )
            return {
                "agent_experience": agent_experience_retriever.retrieve,
                "custom_knowledge": custom_knowledge_retriever.retrieve,
                "external_knowledge": external_knowledge_retriever.retrieve,
                "procedures": procedure_retriever.retrieve,
                "examples": example_retriever.retrieve,
                "policies": policy_retriever.retrieve,
                "user_memory": user_memory_retriever.retrieve,
                "capability_knowledge": capability_retriever.retrieve,
            }
        except Exception as exc:
            logger.warning("Context broker default handlers unavailable: %s", exc)
            return {}
