from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .models import ContextIntent


@dataclass(slots=True)
class IntentClassification:
    """Weak semantic signal bundle produced by IntentClassifier.

    `legacy_intent` exists as a compatibility bridge for callers that still
    expect a ContextIntent, but it is not the semantic authority of the turn.
    """

    legacy_intent: ContextIntent
    hints: List[str] = field(default_factory=list)
    candidate_intents: List[Tuple[ContextIntent, float]] = field(default_factory=list)
    matched_markers: Dict[str, bool] = field(default_factory=dict)
    signal_strength: str = "low"
    semantic_authority: bool = False

    def __iter__(self):
        yield self.legacy_intent
        yield self.hints

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int):
        if index in (0, -2):
            return self.legacy_intent
        if index in (1, -1):
            return self.hints
        raise IndexError(index)

    @property
    def intent(self) -> ContextIntent:
        # Compatibility alias for callers that still expect `.intent`.
        return self.legacy_intent

    @property
    def notes(self) -> List[str]:
        return self.hints


class IntentClassifier:
    """Compatibility classifier that emits weak signals for broker routing."""

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

    def classify(self, user_input: str, session=None) -> IntentClassification:
        text = (user_input or "").strip().lower()
        notes: List[str] = []

        if not text:
            return self._result(
                ContextIntent.CONVERSATIONAL,
                ["empty_input"],
                candidate_intents=[(ContextIntent.CONVERSATIONAL, 0.1)],
                matched_markers={"empty_input": True},
                signal_strength="none",
            )

        if getattr(session, "pending_action", None):
            notes.append("pending_action_present")
            if self._contains_any(text, self._POLICY_MARKERS):
                return self._result(
                    ContextIntent.POLICY_LOOKUP,
                    notes + ["policy_markers"],
                    candidate_intents=[
                        (ContextIntent.POLICY_LOOKUP, 0.95),
                        (ContextIntent.TASK_EXECUTION, 0.45),
                    ],
                    matched_markers={"pending_action_present": True, "policy_markers": True},
                    signal_strength="high",
                )
            return self._result(
                ContextIntent.TASK_EXECUTION,
                notes + ["default_pending_action"],
                candidate_intents=[(ContextIntent.TASK_EXECUTION, 0.7)],
                matched_markers={"pending_action_present": True},
                signal_strength="medium",
            )

        has_task_markers = self._looks_like_multi_step_task(text, session)
        has_custom_knowledge_markers = self._contains_any(text, self._CUSTOM_KNOWLEDGE_MARKERS)
        has_documentation_markers = self._contains_any(text, self._DOCUMENTATION_MARKERS)
        has_strict_policy_markers = self._contains_any(text, self._STRICT_POLICY_MARKERS)

        if self._contains_any(text, self._TROUBLESHOOT_MARKERS):
            return self._result(
                ContextIntent.TROUBLESHOOTING,
                notes + ["troubleshooting_markers"],
                candidate_intents=[(ContextIntent.TROUBLESHOOTING, 0.95)],
                matched_markers={"troubleshooting_markers": True},
                signal_strength="high",
            )

        if has_custom_knowledge_markers and not has_strict_policy_markers:
            if has_task_markers:
                return self._result(
                    ContextIntent.TASK_EXECUTION,
                    notes + ["custom_knowledge_markers", "task_markers", "hybrid_custom_task"],
                    candidate_intents=[
                        (ContextIntent.TASK_EXECUTION, 0.82),
                        (ContextIntent.GENERAL_KNOWLEDGE, 0.55),
                    ],
                    matched_markers={"custom_knowledge_markers": True, "task_markers": True},
                    signal_strength="medium",
                )
            return self._result(
                ContextIntent.GENERAL_KNOWLEDGE,
                notes + ["custom_knowledge_markers"],
                candidate_intents=[(ContextIntent.GENERAL_KNOWLEDGE, 0.75)],
                matched_markers={"custom_knowledge_markers": True},
                signal_strength="medium",
            )

        if has_documentation_markers and not has_strict_policy_markers:
            if has_task_markers:
                return self._result(
                    ContextIntent.TASK_EXECUTION,
                    notes + ["documentation_markers", "task_markers", "hybrid_documentation_task"],
                    candidate_intents=[
                        (ContextIntent.TASK_EXECUTION, 0.8),
                        (ContextIntent.GENERAL_KNOWLEDGE, 0.6),
                    ],
                    matched_markers={"documentation_markers": True, "task_markers": True},
                    signal_strength="medium",
                )
            return self._result(
                ContextIntent.GENERAL_KNOWLEDGE,
                notes + ["documentation_markers"],
                candidate_intents=[(ContextIntent.GENERAL_KNOWLEDGE, 0.74)],
                matched_markers={"documentation_markers": True},
                signal_strength="medium",
            )

        if self._contains_any(text, self._POLICY_MARKERS):
            return self._result(
                ContextIntent.POLICY_LOOKUP,
                notes + ["policy_markers"],
                candidate_intents=[(ContextIntent.POLICY_LOOKUP, 0.9)],
                matched_markers={"policy_markers": True},
                signal_strength="high",
            )

        has_memory_markers = self._contains_any(text, self._MEMORY_MARKERS)

        if has_memory_markers and has_task_markers:
            return self._result(
                ContextIntent.TASK_EXECUTION,
                notes + ["memory_markers", "task_markers", "hybrid_memory_task"],
                candidate_intents=[
                    (ContextIntent.TASK_EXECUTION, 0.78),
                    (ContextIntent.MEMORY_LOOKUP, 0.62),
                ],
                matched_markers={"memory_markers": True, "task_markers": True},
                signal_strength="medium",
            )

        if has_memory_markers:
            return self._result(
                ContextIntent.MEMORY_LOOKUP,
                notes + ["memory_markers"],
                candidate_intents=[(ContextIntent.MEMORY_LOOKUP, 0.9)],
                matched_markers={"memory_markers": True},
                signal_strength="high",
            )

        if self._contains_any(text, self._CAPABILITY_MARKERS):
            return self._result(
                ContextIntent.CAPABILITY_LOOKUP,
                notes + ["capability_markers"],
                candidate_intents=[(ContextIntent.CAPABILITY_LOOKUP, 0.88)],
                matched_markers={"capability_markers": True},
                signal_strength="high",
            )

        if self._contains_any(text, self._GENERAL_KNOWLEDGE_MARKERS) and not self._contains_any(text, self._TASK_MARKERS):
            return self._result(
                ContextIntent.GENERAL_KNOWLEDGE,
                notes + ["general_knowledge_markers"],
                candidate_intents=[(ContextIntent.GENERAL_KNOWLEDGE, 0.82)],
                matched_markers={"general_knowledge_markers": True},
                signal_strength="medium",
            )

        if has_task_markers:
            task_notes = ["task_markers"]
            if getattr(session, "task_registry", None):
                task_notes.append("task_registry_present")
            return self._result(
                ContextIntent.TASK_EXECUTION,
                notes + task_notes,
                candidate_intents=[(ContextIntent.TASK_EXECUTION, 0.72)],
                matched_markers={"task_markers": True},
                signal_strength="medium",
            )

        return self._result(
            ContextIntent.CONVERSATIONAL,
            notes + ["fallback_conversational"],
            candidate_intents=[(ContextIntent.CONVERSATIONAL, 0.55)],
            matched_markers={"fallback_conversational": True},
            signal_strength="low",
        )

    @staticmethod
    def _result(
        legacy_intent: ContextIntent,
        hints: List[str],
        *,
        candidate_intents: List[Tuple[ContextIntent, float]] | None = None,
        matched_markers: Dict[str, bool] | None = None,
        signal_strength: str = "low",
    ) -> IntentClassification:
        return IntentClassification(
            legacy_intent=legacy_intent,
            hints=hints,
            candidate_intents=list(candidate_intents or [(legacy_intent, 0.5)]),
            matched_markers=dict(matched_markers or {}),
            signal_strength=signal_strength,
            semantic_authority=False,
        )

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
