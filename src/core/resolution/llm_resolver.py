from typing import Optional, Dict, Any, List
from .base import IntentResolver
from .action_plan import ActionPlan
from services.llm.manager import LLMManager
import logging

logger = logging.getLogger("LLMResolver")

class LLMResolver(IntentResolver):
    def __init__(self, llm_manager: LLMManager, threshold: float = 0.65, skill_registry: Any = None):
        self.llm_manager = llm_manager
        self.threshold = threshold
        self.skill_registry = skill_registry

    def resolve(self, user_input: str, context: Dict[str, Any]) -> Optional[ActionPlan]:
        session = context.get("session")
        if not session:
            logger.warning("No session provided for LLMResolver")
            return None
        
        system_prompt = context.get("system_prompt", "")
        # Get history from context or session
        history = context.get("history") or session.get_context_for_llm(limit_msgs=5)
        attachments = context.get("attachments")
        local_context = dict(context)
        local_context["user_input"] = user_input
        
        try:
            intent = self.llm_manager.generate_intent(user_input, history, system_prompt, attachments=attachments)
            if not intent:
                return None
            
            confidence, notes = self._estimate_confidence(intent, local_context)
            
            if confidence < self.threshold:
                logger.warning(
                    f"LLM confidence {confidence:.2f} below threshold {self.threshold:.2f} "
                    f"for action '{intent.action}' | notes={notes}"
                )
                return None

            return ActionPlan(
                action_id=intent.action,
                args=intent.params,
                confidence=confidence,
                source="llm",
                response_text=intent.response_text,
                thought=intent.thought,
                attachments=intent.attachments,
                metadata={
                    "plan": intent.plan, 
                    "state_summary": intent.state_summary,
                    "task_label": intent.task_label,
                    "confidence_notes": notes,
                }
            )
        except Exception as e:
            logger.error(f"LLM resolution failed: {e}")
            return None

    def _estimate_confidence(self, intent: Any, context: Dict[str, Any]) -> tuple[float, List[str]]:
        """
        Estimates confidence using runtime evidence instead of a fixed score.
        """
        notes: List[str] = []
        action = (intent.action or "").strip()
        action_lower = action.lower()
        score = 0.35  # Neutral baseline for structured LLM outputs

        if not action:
            notes.append("missing_action")
            return 0.0, notes

        if action_lower == "unknown":
            notes.append("unknown_action")
            return 0.05, notes

        if action_lower == "error":
            notes.append("error_action")
            return 0.20, notes

        if action_lower == "reply":
            if intent.response_text:
                score += 0.35
                notes.append("reply_with_text")
                # Downgrade operational "progress stub" replies for action-oriented prompts.
                text = str(intent.response_text or "").strip().lower()
                user_input = str(context.get("user_input") or "").strip().lower()
                progress_prefixes = (
                    "pesquisando",
                    "procurando",
                    "buscando",
                    "abrindo",
                    "executando",
                    "aguarde",
                    "um momento",
                )
                command_cues = (
                    "abre",
                    "abrir",
                    "toca",
                    "tocar",
                    "play",
                    "reproduz",
                    "reproduzir",
                    "busca",
                    "buscar",
                    "pesquisa",
                    "musica",
                    "música",
                    "deezer",
                    "spotify",
                    "youtube",
                )
                if text.startswith(progress_prefixes) and any(c in user_input for c in command_cues):
                    score -= 0.45
                    notes.append("reply_progress_stub_for_operational_request")
            else:
                has_attachments = isinstance(getattr(intent, "attachments", None), list) and len(intent.attachments) > 0
                if has_attachments:
                    score += 0.28
                    notes.append("reply_with_attachments_no_text")
                else:
                    score -= 0.20
                    notes.append("reply_without_text")
        else:
            allowed_actions = context.get("allowed_actions")
            registry = context.get("skill_registry") or self.skill_registry

            if allowed_actions is not None:
                if action in allowed_actions:
                    score += 0.30
                    notes.append("action_allowed_for_principal")
                else:
                    score -= 0.35
                    notes.append("action_outside_allowed_scope")
            elif registry and hasattr(registry, "get_skill_for_action"):
                if registry.get_skill_for_action(action):
                    score += 0.25
                    notes.append("action_registered")
                else:
                    score -= 0.30
                    notes.append("action_not_registered")

            if isinstance(intent.params, dict):
                if intent.params:
                    score += 0.08
                    notes.append("params_present")
                else:
                    score += 0.02
                    notes.append("params_empty")
            else:
                score -= 0.10
                notes.append("params_not_object")

        thought = (intent.thought or "").strip()
        if len(thought) >= 8:
            score += 0.05
            notes.append("thought_present")
        else:
            score -= 0.03
            notes.append("thought_too_short")

        plan = getattr(intent, "plan", None)
        if isinstance(plan, list) and plan:
            score += 0.03
            notes.append("plan_present")

        # Keep score in [0, 1]
        score = max(0.0, min(1.0, score))
        return score, notes
