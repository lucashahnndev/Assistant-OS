from __future__ import annotations

from typing import List, Tuple

from .models import ContextIntent


class IntentClassifier:
    """Deterministic Phase 1 turn classifier for broker routing."""

    _CAPABILITY_MARKERS = (
        "how to use",
        "how do i use",
        "what can you do",
        "capability",
        "capabilities",
        "action",
        "tool",
        "which tool",
        "does x do",
        "como usar",
        "o que voce faz",
        "o que você faz",
        "capacidade",
        "ferramenta",
    )
    _POLICY_MARKERS = (
        "policy",
        "rule",
        "rules",
        "permission",
        "permissions",
        "approval",
        "allowed",
        "forbidden",
        "can i",
        "why was it blocked",
        "política",
        "regra",
        "regras",
        "permiss",
        "aprova",
        "permitido",
        "bloqueado",
    )
    _STRICT_POLICY_MARKERS = (
        "policy",
        "permission",
        "permissions",
        "approval",
        "allowed",
        "forbidden",
        "why was it blocked",
        "política",
        "permiss",
        "aprova",
        "permitido",
        "bloqueado",
    )
    _MEMORY_MARKERS = (
        "remember",
        "recall",
        "memory",
        "what do you know about me",
        "last time",
        "previously",
        "earlier",
        "lembra",
        "memoria",
        "memória",
        "antes",
        "da outra vez",
    )
    _TROUBLESHOOT_MARKERS = (
        "error",
        "failed",
        "failure",
        "debug",
        "diagnose",
        "issue",
        "problem",
        "not working",
        "broke",
        "troubleshoot",
        "erro",
        "falhou",
        "falha",
        "depurar",
        "problema",
        "não funciona",
        "nao funciona",
    )
    _GENERAL_KNOWLEDGE_MARKERS = (
        "what is",
        "who is",
        "tell me about",
        "capital of",
        "explain",
        "define",
        "que e",
        "que é",
        "quem é",
        "explique",
        "defina",
    )
    _DOCUMENTATION_MARKERS = (
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
        "manual",
        "guia",
        "referência",
        "referencia",
        "especificação",
        "especificacao",
    )
    _CUSTOM_KNOWLEDGE_MARKERS = (
        "our company",
        "our team",
        "our customer",
        "internal rule",
        "business rule",
        "company policy",
        "client onboarding",
        "custom knowledge",
        "teach you",
        "how we do",
        "for our business",
        "nossa empresa",
        "nosso time",
        "nosso cliente",
        "regra interna",
        "regra de negócio",
        "regra de negocio",
        "conhecimento customizado",
        "te ensinar",
        "como fazemos",
    )
    _TASK_MARKERS = (
        "please",
        "create",
        "write",
        "build",
        "implement",
        "run",
        "open",
        "search",
        "fix",
        "update",
        "execute",
        "make",
        "crie",
        "escreva",
        "implemente",
        "rode",
        "abra",
        "pesquise",
        "corrija",
        "atualize",
        "execute",
        "faça",
        "faca",
    )

    def classify(self, user_input: str, session=None) -> Tuple[ContextIntent, List[str]]:
        text = (user_input or "").strip().lower()
        notes: List[str] = []

        if not text:
            return ContextIntent.CONVERSATIONAL, ["empty_input"]

        if getattr(session, "pending_action", None):
            notes.append("pending_action_present")
            if self._contains_any(text, self._POLICY_MARKERS):
                return ContextIntent.POLICY_LOOKUP, notes + ["policy_markers"]
            return ContextIntent.TASK_EXECUTION, notes + ["default_pending_action"]

        has_task_markers = self._looks_like_multi_step_task(text, session)
        has_custom_knowledge_markers = self._contains_any(text, self._CUSTOM_KNOWLEDGE_MARKERS)
        has_documentation_markers = self._contains_any(text, self._DOCUMENTATION_MARKERS)
        has_strict_policy_markers = self._contains_any(text, self._STRICT_POLICY_MARKERS)

        if self._contains_any(text, self._TROUBLESHOOT_MARKERS):
            return ContextIntent.TROUBLESHOOTING, notes + ["troubleshooting_markers"]

        if has_custom_knowledge_markers and not has_strict_policy_markers:
            if has_task_markers:
                return ContextIntent.TASK_EXECUTION, notes + ["custom_knowledge_markers", "task_markers", "hybrid_custom_task"]
            return ContextIntent.GENERAL_KNOWLEDGE, notes + ["custom_knowledge_markers"]

        if has_documentation_markers and not has_strict_policy_markers:
            if has_task_markers:
                return ContextIntent.TASK_EXECUTION, notes + ["documentation_markers", "task_markers", "hybrid_documentation_task"]
            return ContextIntent.GENERAL_KNOWLEDGE, notes + ["documentation_markers"]

        if self._contains_any(text, self._POLICY_MARKERS):
            return ContextIntent.POLICY_LOOKUP, notes + ["policy_markers"]

        has_memory_markers = self._contains_any(text, self._MEMORY_MARKERS)

        if has_memory_markers and has_task_markers:
            return ContextIntent.TASK_EXECUTION, notes + ["memory_markers", "task_markers", "hybrid_memory_task"]

        if has_memory_markers:
            return ContextIntent.MEMORY_LOOKUP, notes + ["memory_markers"]

        if self._contains_any(text, self._CAPABILITY_MARKERS):
            return ContextIntent.CAPABILITY_LOOKUP, notes + ["capability_markers"]

        if self._contains_any(text, self._GENERAL_KNOWLEDGE_MARKERS) and not self._contains_any(text, self._TASK_MARKERS):
            return ContextIntent.GENERAL_KNOWLEDGE, notes + ["general_knowledge_markers"]

        if has_task_markers:
            task_notes = ["task_markers"]
            if getattr(session, "task_registry", None):
                task_notes.append("task_registry_present")
            return ContextIntent.TASK_EXECUTION, notes + task_notes

        return ContextIntent.CONVERSATIONAL, notes + ["fallback_conversational"]

    @classmethod
    def _looks_like_multi_step_task(cls, text: str, session=None) -> bool:
        if cls._contains_any(text, cls._TASK_MARKERS):
            return True
        if len(text.split()) >= 12 and any(token in text for token in (" then ", " depois ", " and ", " e ")):
            return True
        if session and getattr(session, "active_focus_task_id", None):
            return True
        return False

    @staticmethod
    def _contains_any(text: str, markers: Tuple[str, ...]) -> bool:
        return any(marker in text for marker in markers)
