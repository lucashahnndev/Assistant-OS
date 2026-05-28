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
