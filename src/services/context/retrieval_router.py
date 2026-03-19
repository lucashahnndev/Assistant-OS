from __future__ import annotations

from typing import Dict, List

from .models import ContextIntent, RetrievalTarget


class RetrievalRouter:
    """Maps classified intent to logical retrieval domains."""

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

    _ROUTES: Dict[ContextIntent, List[RetrievalTarget]] = {
        ContextIntent.TASK_EXECUTION: [
            RetrievalTarget(domain="procedures", priority=1, max_results=2),
            RetrievalTarget(domain="capability_knowledge", priority=2, max_results=3),
            RetrievalTarget(domain="user_memory", priority=3, max_results=2),
            RetrievalTarget(domain="agent_experience", priority=4, max_results=1, active=False, notes="troubleshooting_hint"),
            RetrievalTarget(domain="custom_knowledge", priority=5, max_results=1, active=False, notes="custom_hint"),
            RetrievalTarget(domain="external_knowledge", priority=6, max_results=1, active=False, notes="documentation_hint"),
            RetrievalTarget(domain="policies", priority=7, max_results=1, active=False, notes="query_activated"),
        ],
        ContextIntent.CAPABILITY_LOOKUP: [
            RetrievalTarget(domain="capability_knowledge", priority=1, max_results=5),
            RetrievalTarget(domain="examples", priority=2, max_results=2),
            RetrievalTarget(domain="external_knowledge", priority=3, max_results=1, active=False, notes="documentation_hint"),
            RetrievalTarget(domain="policies", priority=4, max_results=1, active=False, notes="query_activated"),
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
            RetrievalTarget(domain="policies", priority=8, max_results=1),
        ],
        ContextIntent.CONVERSATIONAL: [
            RetrievalTarget(domain="user_memory", priority=1, max_results=1),
        ],
        ContextIntent.GENERAL_KNOWLEDGE: [
            RetrievalTarget(domain="external_knowledge", priority=1, max_results=3),
            RetrievalTarget(domain="custom_knowledge", priority=2, max_results=2, active=False, notes="custom_hint"),
        ],
    }

    def route(self, intent: ContextIntent, user_input: str = "", broker_hints: Dict[str, object] | None = None) -> List[RetrievalTarget]:
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
        return hinted_targets

    @classmethod
    def _is_policy_relevant(cls, user_input: str) -> bool:
        text = (user_input or "").lower()
        return any(marker in text for marker in cls._POLICY_HINTS)

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
        text = (user_input or "").lower()
        return any(marker in text for marker in RetrievalRouter._DOCUMENTATION_HINTS)

    @staticmethod
    def _is_custom_knowledge_relevant(user_input: str) -> bool:
        text = (user_input or "").lower()
        return any(marker in text for marker in RetrievalRouter._CUSTOM_KNOWLEDGE_HINTS)

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
        if target.domain == "policies" and not target.active:
            return policy_relevant or bool(hints.get("approval_pending"))
        if target.domain == "agent_experience" and not target.active:
            return troubleshooting_relevant or bool(hints.get("troubleshooting_active"))
        if target.domain == "external_knowledge" and not target.active:
            return documentation_relevant
        if target.domain == "custom_knowledge" and not target.active:
            return custom_relevant
        return target.active

    @staticmethod
    def _hinted_priority(target: RetrievalTarget, broker_hints: Dict[str, object] | None) -> int:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        priority = int(target.priority)
        if target.domain == "agent_experience" and bool(hints.get("troubleshooting_active")):
            priority -= 1
        if target.domain == "policies" and bool(hints.get("approval_pending")):
            priority -= 1
        if target.domain == "capability_knowledge" and str(hints.get("hot_action_namespace") or "").strip():
            priority -= 1
        if target.domain == "procedures" and str(hints.get("primary_task_id") or "").strip():
            priority -= 1
        return max(1, priority)

    @staticmethod
    def _hinted_notes(target: RetrievalTarget, broker_hints: Dict[str, object] | None) -> str:
        hints = broker_hints if isinstance(broker_hints, dict) else {}
        notes = str(target.notes or "").strip()
        applied = []
        if target.domain == "agent_experience" and bool(hints.get("troubleshooting_active")):
            applied.append("hint:troubleshooting")
        if target.domain == "policies" and bool(hints.get("approval_pending")):
            applied.append("hint:approval")
        if target.domain == "capability_knowledge" and str(hints.get("hot_action_namespace") or "").strip():
            applied.append("hint:namespace")
        if target.domain == "procedures" and str(hints.get("primary_task_id") or "").strip():
            applied.append("hint:focus")
        if not applied:
            return notes
        if notes:
            return notes + "|" + "|".join(applied)
        return "|".join(applied)
