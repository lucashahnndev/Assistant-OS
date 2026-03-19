from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any, Dict, List, Sequence, Tuple

from .control_plane import ProviderControlPlane
from .models import ExecutionBudgets, PlanStep, RetrievalPlan, RoutingDecision


@dataclass(slots=True)
class ProviderSpec:
    id: str
    domains: Tuple[str, ...]
    action_id: str = ""
    strategy: str = "direct_results"
    setup_ready: bool = True
    trust_tier: str = "medium"


class ExternalRAGPlanner:
    """Phase 2 planner: deterministic intent + control plane + explicit score routing."""

    _TRUST_WEIGHTS = {"high": 1.0, "medium": 0.8, "low": 0.55}

    def classify_intent(self, query: str) -> Tuple[str, str]:
        text = (query or "").strip().lower()
        if any(
            marker in text
            for marker in (
                "música",
                "musica",
                "music",
                "song",
                "track",
                "artist",
                "album",
                "playlist",
                "spotify",
                "deezer",
            )
        ):
            return "music_lookup", "catalog_search"
        if any(marker in text for marker in ("preço", "price", "cotação", "quote", "valor")):
            return "structured_fact", "numeric_fact"
        if any(marker in text for marker in ("latest", "recent", "today", "hoje", "atual", "últim", "ultim")):
            return "latest_update", "time_sensitive"
        if any(marker in text for marker in ("video", "vídeo", "youtube", "watch", "comparativo")):
            return "media_lookup", "video_search"
        if any(marker in text for marker in ("where", "onde", "maps", "mapa", "near", "perto")):
            return "location_lookup", "place_search"
        if any(marker in text for marker in ("paper", "doi", "openalex", "study", "academic", "artigo")):
            return "academic_lookup", "citation_search"
        if any(marker in text for marker in ("who is", "quem é", "what is", "o que é", "entity", "entidade")):
            return "entity_lookup", "entity_definition"
        return "general_knowledge", "broad_lookup"

    @staticmethod
    def intent_to_domain(intent: str) -> str:
        return ExternalRAGPlanner._intent_domain(intent)

    def decompose_query(self, query: str, intent: str, subintent: str) -> List[PlanStep]:
        text = (query or "").strip()
        separators = [" e ", " and ", ","]
        parts = [text]
        for sep in separators:
            if sep in text.lower():
                split_parts = [chunk.strip() for chunk in text.split(sep) if chunk.strip()]
                if 1 < len(split_parts) <= 3:
                    parts = split_parts
                    break

        steps: List[PlanStep] = []
        for idx, part in enumerate(parts, start=1):
            step_intent, step_subintent = self.classify_intent(part)
            if len(parts) == 1:
                step_intent = intent
                step_subintent = subintent
            steps.append(
                PlanStep(
                    step_id=f"step_{idx}",
                    query=part,
                    intent=step_intent,
                    subintent=step_subintent,
                )
            )
        return steps

    def build_plan(
        self,
        *,
        query: str,
        constraints: Dict[str, Any],
        providers: Sequence[ProviderSpec],
    ) -> Tuple[RetrievalPlan, List[RoutingDecision]]:
        intent, subintent = self.classify_intent(query)
        steps = self.decompose_query(query=query, intent=intent, subintent=subintent)
        control_plane = ProviderControlPlane.from_constraints(constraints)
        broad_recovery = str(constraints.get("replan_mode") or "").strip().lower() == "broad_recovery"

        budgets = self._build_budgets(intent=intent, constraints=constraints)
        decisions = self._rank_providers(
            intent=intent,
            providers=providers,
            budgets=budgets,
            control_plane=control_plane,
            broad_recovery=broad_recovery,
        )
        selected = [item.provider for item in decisions if item.used]
        fallback_chain = [item.provider for item in decisions if not item.used and item.reason == "lower_score"]

        for step in steps:
            step.selected_providers = list(selected)

        plan = RetrievalPlan(
            query_id=self._query_id(query),
            intent=intent,
            subintent=subintent,
            constraints=dict(constraints),
            plan_steps=steps,
            selected_providers=selected,
            merge_strategy=self._merge_strategy(intent),
            fallback_chain=fallback_chain[: budgets.max_fallback_depth],
            budgets=budgets,
            provider_runtime_scorecard=control_plane.to_trace(),
            explanation_trace=[item.to_dict() for item in decisions],
        )
        return plan, decisions

    def _build_budgets(self, *, intent: str, constraints: Dict[str, Any]) -> ExecutionBudgets:
        max_providers = int(constraints.get("max_providers") or 2)
        max_fallback_depth = int(constraints.get("max_fallback_depth") or 2)
        max_retries = int(constraints.get("max_retries") or 1)

        if intent in {"latest_update", "structured_fact"}:
            default_latency = 9000
        elif intent == "media_lookup":
            default_latency = 11000
        else:
            default_latency = 12000

        return ExecutionBudgets(
            latency_budget_ms=int(constraints.get("latency_budget_ms") or default_latency),
            cost_budget=float(constraints.get("cost_budget") or 0.0),
            max_providers=max(1, min(3, max_providers)),
            max_fallback_depth=max(1, min(4, max_fallback_depth)),
            max_parallelism=1,
            max_retries=max(0, min(2, max_retries)),
        )

    def _rank_providers(
        self,
        *,
        intent: str,
        providers: Sequence[ProviderSpec],
        budgets: ExecutionBudgets,
        control_plane: ProviderControlPlane,
        broad_recovery: bool,
    ) -> List[RoutingDecision]:
        intent_domain = self._intent_domain(intent)
        scored: List[RoutingDecision] = []

        for provider in providers:
            runtime_state = control_plane.state_for(provider.id)
            setup_factor = 1.0 if (provider.setup_ready and runtime_state.setup_ready) else 0.0
            intent_match = 1.0 if intent_domain in provider.domains else (0.45 if broad_recovery else 0.2)
            trust = self._TRUST_WEIGHTS.get(provider.trust_tier, 0.65)
            runtime_health = runtime_state.runtime_health
            success_rate = runtime_state.success_rate
            latency_score = self._latency_score(runtime_state.latency_ms)
            # NOTE: learning/adaptive factors are capped to avoid dominance/overfitting.
            historical = min(0.7, max(0.3, runtime_state.historical_performance))
            user_context = max(0.0, min(1.0, runtime_state.user_context_boost))
            score = (
                (0.35 * intent_match)
                + (0.20 * trust)
                + (0.15 * setup_factor)
                + (0.15 * runtime_health)
                + (0.10 * success_rate)
                + (0.05 * latency_score)
                + (0.02 * user_context)
                + (0.03 * historical)
            )
            if runtime_state.degraded:
                score = score * 0.82

            reason = "selected"
            used = True
            if runtime_state.disabled:
                used = False
                reason = "disabled"
            elif runtime_state.quota_exceeded:
                used = False
                reason = "quota_exceeded"
            elif runtime_state.error_previous:
                used = False
                reason = "error_previous"
            elif runtime_state.force_fallback:
                used = False
                reason = "force_fallback"
            elif setup_factor <= 0:
                used = False
                reason = "requires_setup"
            elif intent_match < 0.4:
                used = False
                reason = "intent_mismatch"
            elif broad_recovery and intent_domain not in provider.domains:
                reason = "selected_replan_cross_domain"

            scored.append(
                RoutingDecision(
                    provider=provider.id,
                    used=used,
                    reason=reason,
                    score=round(score, 4),
                    score_breakdown={
                        "intent_match": round(intent_match, 4),
                        "trust_tier": round(trust, 4),
                        "setup_ready": round(setup_factor, 4),
                        "runtime_health": round(runtime_health, 4),
                        "success_rate": round(success_rate, 4),
                        "latency_score": round(latency_score, 4),
                        "user_context": round(user_context, 4),
                        "historical_performance": round(historical, 4),
                        "degraded_penalty": 0.82 if runtime_state.degraded else 1.0,
                    },
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)

        selected = 0
        for item in scored:
            if item.reason != "selected":
                continue
            if selected >= budgets.max_providers:
                item.used = False
                item.reason = "lower_score"
                continue
            selected += 1

        return scored

    @staticmethod
    def _latency_score(latency_ms: int) -> float:
        if latency_ms <= 250:
            return 1.0
        if latency_ms <= 700:
            return 0.8
        if latency_ms <= 1400:
            return 0.6
        if latency_ms <= 2600:
            return 0.4
        return 0.2

    @staticmethod
    def _intent_domain(intent: str) -> str:
        mapping = {
            "general_knowledge": "web",
            "entity_lookup": "encyclopedia",
            "latest_update": "web",
            "structured_fact": "web",
            "media_lookup": "video",
            "music_lookup": "music",
            "location_lookup": "location",
            "academic_lookup": "academic",
        }
        return mapping.get(intent, "web")

    @staticmethod
    def _merge_strategy(intent: str) -> str:
        if intent == "latest_update":
            return "recency_first"
        if intent == "structured_fact":
            return "trust_then_consensus"
        if intent == "entity_lookup":
            return "authority_first"
        return "synthesize_with_citations"

    @staticmethod
    def _query_id(query: str) -> str:
        text = (query or "").strip().lower().encode("utf-8")
        return sha1(text).hexdigest()[:16]
