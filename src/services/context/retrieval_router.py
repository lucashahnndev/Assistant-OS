from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .models import ContextIntent, RetrievalTarget


@dataclass(slots=True)
class RetrievalRouteSignals:
    """Weak retrieval guidance produced by RetrievalRouter.

    `legacy_intent` exists for compatibility with the current pipeline, but the
    semantic decision remains external to the router.
    """

    legacy_intent: ContextIntent
    targets: List[RetrievalTarget] = field(default_factory=list)
    candidate_domains: List[str] = field(default_factory=list)
    domain_weights: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    source_hints: List[str] = field(default_factory=list)
    matched_markers: Dict[str, bool] = field(default_factory=dict)
    uncertainty: str = "low"
    semantic_authority: bool = False

    def __iter__(self):
        return iter(self.targets)

    def __len__(self) -> int:
        return len(self.targets)

    def __getitem__(self, index: int) -> RetrievalTarget:
        return self.targets[index]

    @property
    def intent(self) -> ContextIntent:
        return self.legacy_intent

    @property
    def notes(self) -> List[str]:
        return self.reasons


class RetrievalRouter:
    """Produces retrieval candidates and weak evidence signals."""

    _DOCUMENTATION_HINTS = (
        "documentation",
        "docs",
        "readme",
        "manual",
        "guide",
        "reference",
        "knowledge base",
        "spec",
        "specification",
        "documentação",
        "documentacao",
        "guia",
        "referência",
        "referencia",
        "especificação",
        "especificacao",
    )
    _CUSTOM_KNOWLEDGE_HINTS = (
        "our company",
        "our team",
        "our process",
        "our customer",
        "business rule",
        "internal rule",
        "company-specific",
        "customer-specific",
        "custom knowledge",
        "teach you",
        "client onboarding",
        "nossa empresa",
        "nosso time",
        "nosso processo",
        "nosso cliente",
        "regra interna",
        "regra de negócio",
        "regra de negocio",
        "conhecimento customizado",
        "te ensinar",
    )
    _POLICY_HINTS = (
        "policy",
        "policies",
        "permission",
        "permissions",
        "approval",
        "governance",
        "allowed",
        "forbidden",
        "risk",
        "high-risk",
        "acl",
        "regra",
        "regras",
        "política",
        "permiss",
        "aprova",
        "govern",
        "risco",
    )
    _HINT_RULES = {
        "policies": {
            "active": ("approval_pending",),
            "priority": ("approval_pending", -1),
            "note": ("approval_pending", "hint:approval"),
        },
        "agent_experience": {
            "active": ("troubleshooting_active",),
            "priority": ("troubleshooting_active", -1),
            "note": ("troubleshooting_active", "hint:troubleshooting"),
        },
        "external_knowledge": {
            "active_relevance": ("documentation_relevant",),
        },
        "custom_knowledge": {
            "active_relevance": ("custom_relevant",),
        },
        "mcp_resources": {
            "active_relevance_any": ("documentation_relevant", "custom_relevant"),
        },
        "capability_knowledge": {
            "priority": ("hot_action_namespace", -1),
            "note": ("hot_action_namespace", "hint:namespace"),
        },
        "procedures": {
            "priority": ("primary_task_id", -1),
            "note": ("primary_task_id", "hint:focus"),
        },
    }

    _ROUTES: Dict[ContextIntent, List[RetrievalTarget]] = {
        ContextIntent.TASK_EXECUTION: [
            RetrievalTarget(domain="procedures", priority=1, max_results=2),
            RetrievalTarget(domain="capability_knowledge", priority=2, max_results=3),
            RetrievalTarget(domain="user_memory", priority=3, max_results=2),
            RetrievalTarget(domain="agent_experience", priority=4, max_results=1, active=False, notes="troubleshooting_hint"),
            RetrievalTarget(domain="custom_knowledge", priority=5, max_results=1, active=False, notes="custom_hint"),
            RetrievalTarget(domain="external_knowledge", priority=6, max_results=1, active=False, notes="documentation_hint"),
            RetrievalTarget(domain="mcp_resources", priority=7, max_results=1, active=False, notes="resource_hint"),
            RetrievalTarget(domain="policies", priority=8, max_results=1, active=False, notes="query_activated"),
        ],
        ContextIntent.CAPABILITY_LOOKUP: [
            RetrievalTarget(domain="capability_knowledge", priority=1, max_results=5),
            RetrievalTarget(domain="examples", priority=2, max_results=2),
            RetrievalTarget(domain="external_knowledge", priority=3, max_results=1, active=False, notes="documentation_hint"),
            RetrievalTarget(domain="mcp_resources", priority=4, max_results=1, active=False, notes="resource_hint"),
            RetrievalTarget(domain="policies", priority=5, max_results=1, active=False, notes="query_activated"),
        ],
        ContextIntent.POLICY_LOOKUP: [
            RetrievalTarget(domain="policies", priority=1, max_results=3),
            RetrievalTarget(domain="capability_knowledge", priority=2, max_results=2),
        ],
        ContextIntent.MEMORY_LOOKUP: [
            RetrievalTarget(domain="user_memory", priority=1, max_results=4),
        ],
        ContextIntent.TROUBLESHOOTING: [
            RetrievalTarget(domain="agent_experience", priority=1, max_results=2),
            RetrievalTarget(domain="procedures", priority=2, max_results=2),
            RetrievalTarget(domain="capability_knowledge", priority=3, max_results=2),
            RetrievalTarget(domain="user_memory", priority=4, max_results=2),
            RetrievalTarget(domain="examples", priority=5, max_results=1),
            RetrievalTarget(domain="external_knowledge", priority=6, max_results=1, active=False, notes="documentation_hint"),
            RetrievalTarget(domain="custom_knowledge", priority=7, max_results=1, active=False, notes="custom_hint"),
            RetrievalTarget(domain="mcp_resources", priority=8, max_results=1, active=False, notes="resource_hint"),
            RetrievalTarget(domain="policies", priority=9, max_results=1),
        ],
        ContextIntent.CONVERSATIONAL: [
            RetrievalTarget(domain="user_memory", priority=1, max_results=1),
        ],
        ContextIntent.GENERAL_KNOWLEDGE: [
            RetrievalTarget(domain="external_knowledge", priority=1, max_results=3),
            RetrievalTarget(domain="custom_knowledge", priority=2, max_results=2, active=False, notes="custom_hint"),
            RetrievalTarget(domain="mcp_resources", priority=3, max_results=2, active=False, notes="resource_hint"),
        ],
    }

    def route(
        self,
        intent: ContextIntent,
        user_input: str = "",
        broker_hints: Dict[str, object] | None = None,
    ) -> RetrievalRouteSignals:
        targets = self._ROUTES.get(intent, [])
        policy_relevant = self._is_policy_relevant(user_input)
        troubleshooting_relevant = self._is_troubleshooting_relevant(user_input)
        documentation_relevant = self._is_documentation_relevant(user_input)
        custom_relevant = self._is_custom_knowledge_relevant(user_input)
        hinted_targets = [
            RetrievalTarget(
                domain=target.domain,
                priority=self._hinted_priority(target=target, broker_hints=broker_hints),
                max_results=target.max_results,
                filters=dict(target.filters),
                active=self._resolve_active(
                    target=target,
                    policy_relevant=policy_relevant,
                    troubleshooting_relevant=troubleshooting_relevant,
                    documentation_relevant=documentation_relevant,
                    custom_relevant=custom_relevant,
                    broker_hints=broker_hints,
                ),
                notes=self._hinted_notes(target=target, broker_hints=broker_hints),
            )
            for target in targets
        ]
        candidate_domains = [target.domain for target in hinted_targets]
        domain_weights = {
            target.domain: self._hinted_weight(target=target, broker_hints=broker_hints)
            for target in hinted_targets
        }
        reasons = self._build_route_reasons(
            intent=intent,
            user_input=user_input,
            policy_relevant=policy_relevant,
            troubleshooting_relevant=troubleshooting_relevant,
            documentation_relevant=documentation_relevant,
            custom_relevant=custom_relevant,
            broker_hints=broker_hints,
            targets=hinted_targets,
        )
        source_hints = self._build_source_hints(
            intent=intent,
            policy_relevant=policy_relevant,
            troubleshooting_relevant=troubleshooting_relevant,
            documentation_relevant=documentation_relevant,
            custom_relevant=custom_relevant,
            broker_hints=broker_hints,
        )
        uncertainty = self._infer_uncertainty(targets=hinted_targets, broker_hints=broker_hints)
        matched_markers = {
            "policy_relevant": policy_relevant,
            "troubleshooting_relevant": troubleshooting_relevant,
            "documentation_relevant": documentation_relevant,
            "custom_relevant": custom_relevant,
        }
        return RetrievalRouteSignals(
            legacy_intent=intent,
            targets=hinted_targets,
            candidate_domains=candidate_domains,
            domain_weights=domain_weights,
            reasons=reasons,
            source_hints=source_hints,
            matched_markers=matched_markers,
            uncertainty=uncertainty,
            semantic_authority=False,
        )

    @classmethod
    def _is_policy_relevant(cls, user_input: str) -> bool:
        return cls._matches_query_hint(user_input, cls._POLICY_HINTS)

    @staticmethod
    def _is_troubleshooting_relevant(user_input: str) -> bool:
        text = (user_input or "").lower()
        markers = (
            "troubleshoot",
            "debug",
            "fix",
            "failure",
            "error",
            "stuck",
            "recover",
            "retry",
            "timeout",
            "problema",
            "erro",
            "falha",
            "recuper",
            "repet",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _is_documentation_relevant(user_input: str) -> bool:
        return RetrievalRouter._matches_query_hint(user_input, RetrievalRouter._DOCUMENTATION_HINTS)

    @staticmethod
    def _is_custom_knowledge_relevant(user_input: str) -> bool:
        return RetrievalRouter._matches_query_hint(user_input, RetrievalRouter._CUSTOM_KNOWLEDGE_HINTS)

    @staticmethod
    def _matches_query_hint(user_input: str, markers: tuple[str, ...]) -> bool:
        text = (user_input or "").lower()
        return any(marker in text for marker in markers)

    @staticmethod
    def _resolve_hint_value(
        *,
        name: str,
        hints: Dict[str, object],
        policy_relevant: bool,
        troubleshooting_relevant: bool,
        documentation_relevant: bool,
        custom_relevant: bool,
    ) -> bool:
        return bool(
            policy_relevant if name == "policy_relevant" else
            troubleshooting_relevant if name == "troubleshooting_relevant" else
            documentation_relevant if name == "documentation_relevant" else
            custom_relevant if name == "custom_relevant" else
            hints.get(name)
        )

    @staticmethod
    def _resolve_active(
        *,
        target: RetrievalTarget,
        policy_relevant: bool,
        troubleshooting_relevant: bool,
        documentation_relevant: bool,
        custom_relevant: bool,
        broker_hints: Dict[str, object] | None = None,
    ) -> bool:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        if target.active:
            return True
        rule = RetrievalRouter._HINT_RULES.get(target.domain, {})
        if not rule:
            return False
        active_hint = rule.get("active")
        if active_hint:
            return any(bool(hints.get(name)) for name in active_hint)
        active_relevance = rule.get("active_relevance")
        if active_relevance:
            return any(
                RetrievalRouter._resolve_hint_value(
                    name=name,
                    hints=hints,
                    policy_relevant=policy_relevant,
                    troubleshooting_relevant=troubleshooting_relevant,
                    documentation_relevant=documentation_relevant,
                    custom_relevant=custom_relevant,
                )
                for name in active_relevance
            )
        active_any = rule.get("active_relevance_any")
        if active_any:
            return any(
                RetrievalRouter._resolve_hint_value(
                    name=name,
                    hints=hints,
                    policy_relevant=policy_relevant,
                    troubleshooting_relevant=troubleshooting_relevant,
                    documentation_relevant=documentation_relevant,
                    custom_relevant=custom_relevant,
                )
                for name in active_any
            )
        return False
        

    @staticmethod
    def _hinted_priority(target: RetrievalTarget, broker_hints: Dict[str, object] | None) -> int:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        priority = int(target.priority)
        rule = RetrievalRouter._HINT_RULES.get(target.domain, {})
        delta_rule = rule.get("priority")
        if delta_rule:
            hint_name, delta = delta_rule
            value = str(hints.get(hint_name) or "").strip() if hint_name in {"hot_action_namespace", "primary_task_id"} else hints.get(hint_name)
            if value:
                priority += int(delta)
        return max(1, priority)

    @staticmethod
    def _hinted_notes(target: RetrievalTarget, broker_hints: Dict[str, object] | None) -> str:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        notes = str(target.notes or "").strip()
        applied = []
        rule = RetrievalRouter._HINT_RULES.get(target.domain, {})
        note_rule = rule.get("note")
        if note_rule:
            hint_name, note_tag = note_rule
            if RetrievalRouter._resolve_hint_value(
                name=hint_name,
                hints=hints,
                policy_relevant=False,
                troubleshooting_relevant=False,
                documentation_relevant=False,
                custom_relevant=False,
            ):
                applied.append(note_tag)
        if not applied:
            return notes
        if notes:
            return notes + "|" + "|".join(applied)
        return "|".join(applied)

    @staticmethod
    def _hinted_weight(target: RetrievalTarget, broker_hints: Dict[str, object] | None) -> float:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        weight = 1.0 / max(1, int(target.priority))
        if target.domain == "policies" and bool(hints.get("approval_pending")):
            weight += 0.15
        if target.domain == "agent_experience" and bool(hints.get("troubleshooting_active")):
            weight += 0.15
        if target.domain == "capability_knowledge" and hints.get("hot_action_namespace"):
            weight += 0.1
        if target.domain == "procedures" and hints.get("primary_task_id"):
            weight += 0.1
        return round(weight, 3)

    @staticmethod
    def _build_route_reasons(
        *,
        intent: ContextIntent,
        user_input: str,
        policy_relevant: bool,
        troubleshooting_relevant: bool,
        documentation_relevant: bool,
        custom_relevant: bool,
        broker_hints: Dict[str, object] | None,
        targets: List[RetrievalTarget],
    ) -> List[str]:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        reasons = [
            f"intent:{intent.value}",
            f"policy_relevant:{str(policy_relevant).lower()}",
            f"troubleshooting_relevant:{str(troubleshooting_relevant).lower()}",
            f"documentation_relevant:{str(documentation_relevant).lower()}",
            f"custom_relevant:{str(custom_relevant).lower()}",
        ]
        for key in ("approval_pending", "troubleshooting_active", "hot_action_namespace", "primary_task_id"):
            if hints.get(key):
                reasons.append(f"hint:{key}")
        for target in targets[:6]:
            if target.notes:
                reasons.append(f"{target.domain}:{target.notes}")
        text = (user_input or "").strip()
        if text:
            reasons.append(f"query_len:{len(text.split())}")
        return list(dict.fromkeys(reasons))[:10]

    @staticmethod
    def _build_source_hints(
        *,
        intent: ContextIntent,
        policy_relevant: bool,
        troubleshooting_relevant: bool,
        documentation_relevant: bool,
        custom_relevant: bool,
        broker_hints: Dict[str, object] | None,
    ) -> List[str]:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        source_hints = [f"legacy_intent:{intent.value}"]
        if policy_relevant:
            source_hints.append("policy_marker")
        if troubleshooting_relevant:
            source_hints.append("troubleshooting_marker")
        if documentation_relevant:
            source_hints.append("documentation_marker")
        if custom_relevant:
            source_hints.append("custom_marker")
        for key in ("approval_pending", "troubleshooting_active", "hot_action_namespace", "primary_task_id"):
            if hints.get(key):
                source_hints.append(f"broker_hint:{key}")
        return list(dict.fromkeys(source_hints))[:10]

    @staticmethod
    def _infer_uncertainty(*, targets: List[RetrievalTarget], broker_hints: Dict[str, object] | None) -> str:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        if not targets:
            return "high"
        if bool(hints):
            return "medium"
        if any(not target.active for target in targets):
            return "medium"
        return "low"
