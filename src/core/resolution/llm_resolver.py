from typing import Optional, Dict, Any, List
from .base import IntentResolver
from .action_plan import ActionPlan
from services.llm.manager import LLMManager
from core.errors import AgentError, ErrorCode
import logging

logger = logging.getLogger("LLMResolver")

class LLMResolver(IntentResolver):
    _CONFIDENCE_RULES = {
        "reply": {
            "with_text": (0.35, "reply_with_text"),
            "with_attachments_no_text": (0.28, "reply_with_attachments_no_text"),
            "with_thought_only": (0.15, "reply_with_thought_only"),
            "without_text_or_thought": (-0.20, "reply_without_text_or_thought"),
        },
        "action": {
            "allowed_for_principal": (0.30, "action_allowed_for_principal"),
            "outside_allowed_scope": (-0.35, "action_outside_allowed_scope"),
            "registered": (0.25, "action_registered"),
            "not_registered": (-0.30, "action_not_registered"),
            "params_present": (0.08, "params_present"),
            "params_empty": (0.02, "params_empty"),
            "params_not_object": (-0.10, "params_not_object"),
        },
        "thought": {
            "present": (0.05, "thought_present"),
            "too_short": (-0.03, "thought_too_short"),
        },
        "plan": {
            "present": (0.03, "plan_present"),
        },
    }

    def __init__(self, llm_manager: LLMManager, threshold: float = 0.65, capability_registry: Any = None):
        self.llm_manager = llm_manager
        self.threshold = threshold
        self.capability_registry = capability_registry

    def resolve(self, user_input: str, context: Dict[str, Any], attempt: int = 1) -> Optional[ActionPlan]:
        session = context.get("session")
        if not session:
            logger.warning("No session provided for LLMResolver")
            return None

        # Get limits from active instance in manager
        active_config = self.llm_manager.get_active_config()
        max_context = int(active_config.get("max_context", 8000))
        
        # History strategy: try to keep history within 40% of context to leave room for system prompt and output
        history_budget = int(max_context * 0.4)
        
        # Get history from context or session
        history = context.get("history") or session.get_context_for_llm(limit_tokens=history_budget, limit_msgs=5)
        system_prompt = context.get("system_prompt", "")
        attachments = context.get("attachments")
        local_context = dict(context)
        local_context["user_input"] = user_input
        
        try:
            intent = self.llm_manager.generate_intent(user_input, history, system_prompt, attachments=attachments)
            if not intent:
                return None
            
            # Semantic Validation
            if not intent.action or not str(intent.action).strip():
                raise ValueError("Provider returned an invalid action_id.")

            canonical_action = self._canonicalize_action_id(intent.action, local_context)
            if canonical_action != intent.action:
                logger.info(
                    "LLM action canonicalized | raw=%s canonical=%s",
                    intent.action,
                    canonical_action,
                )
                intent.action = canonical_action

            # Prevent pure hallucination loops where intent is just an empty dict parsed as reply
            if intent.action == "reply" and not intent.response_text and not intent.thought:
                 raise ValueError("VALIDATION_ERROR: Empty 'reply' action. Provider must provide either 'response_text' or 'thought'.")

            confidence, notes = self._estimate_confidence(intent, local_context)
            
            if confidence < self.threshold:
                logger.warning(
                    f"LLM confidence {confidence:.2f} below threshold {self.threshold:.2f} "
                    f"for action '{intent.action}' | notes={notes}"
                )
                return ActionPlan(
                    action_id="error",
                    confidence=confidence,
                    source="llm_low_confidence",
                    model_used=intent.model_used,
                    metadata={"error_code": "low_confidence", "notes": notes, "attempted_action": intent.action}
                )

            return ActionPlan(
                action_id=canonical_action,
                args=intent.params,
                confidence=confidence,
                source="llm",
                response_text=intent.response_text,
                thought=intent.thought,
                attachments=intent.attachments,
                model_used=intent.model_used,
                metadata={
                    "plan": intent.plan, 
                    "state_summary": intent.state_summary,
                    "task_label": intent.task_label,
                    "confidence_notes": notes,
                }
            )
        except Exception as e:
            logger.error(f"LLM resolution failed: {e}")
            # The Orchestrator handles high-level recovery/fallback.
            # We return an ActionPlan(action_id="error") to signal failure to the kernel.
            error_code = ErrorCode.PLANNER_SCHEMA_MISMATCH if "json" in str(e).lower() else ErrorCode.UNKNOWN_ERROR
            return ActionPlan(
                action_id="error",
                args={},
                source="llm_error",
                thought=f"Planning failed: {str(e)}",
                metadata={"error_code": error_code.value}
            )

    def _canonicalize_action_id(self, action_id: str, context: Dict[str, Any]) -> str:
        raw = str(action_id or "").strip()
        if not raw:
            return raw
        registry = context.get("capability_registry") or self.capability_registry
        if registry and hasattr(registry, "resolve_action_id"):
            resolved = registry.resolve_action_id(raw)
            if resolved:
                return resolved
        return raw

    @staticmethod
    def _normalize_allowed_actions(allowed_actions: Any, registry: Any) -> set[str]:
        normalized: set[str] = set()
        if not isinstance(allowed_actions, list):
            return normalized
        for item in allowed_actions:
            raw = str(item or "").strip().lower()
            if not raw:
                continue
            resolved = raw
            if registry and hasattr(registry, "resolve_action_id"):
                resolved = str(registry.resolve_action_id(raw) or raw).strip().lower()
            if resolved:
                normalized.add(resolved)
        return normalized

    def _estimate_confidence(self, intent: Any, context: Dict[str, Any]) -> tuple[float, List[str]]:
        """
        Estimates confidence using runtime evidence instead of a fixed score.
        """
        notes: List[str] = []
        action = self._canonicalize_action_id(intent.action, context)
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
                delta, note = self._CONFIDENCE_RULES["reply"]["with_text"]
                score += delta
                notes.append(note)
            else:
                has_attachments = isinstance(getattr(intent, "attachments", None), list) and len(intent.attachments) > 0
                if has_attachments:
                    delta, note = self._CONFIDENCE_RULES["reply"]["with_attachments_no_text"]
                    score += delta
                    notes.append(note)
                elif intent.thought:
                    delta, note = self._CONFIDENCE_RULES["reply"]["with_thought_only"]
                    score += delta
                    notes.append(note)
                else:
                    delta, note = self._CONFIDENCE_RULES["reply"]["without_text_or_thought"]
                    score += delta
                    notes.append(note)
        else:
            allowed_actions = context.get("allowed_actions")
            registry = context.get("capability_registry") or self.capability_registry

            if allowed_actions is not None:
                allowed_set = self._normalize_allowed_actions(allowed_actions, registry)
                if action in allowed_set:
                    delta, note = self._CONFIDENCE_RULES["action"]["allowed_for_principal"]
                    score += delta
                    notes.append(note)
                else:
                    delta, note = self._CONFIDENCE_RULES["action"]["outside_allowed_scope"]
                    score += delta
                    notes.append(note)
            elif registry and hasattr(registry, "get_capability_for_action"):
                if registry.get_capability_for_action(action):
                    delta, note = self._CONFIDENCE_RULES["action"]["registered"]
                    score += delta
                    notes.append(note)
                else:
                    delta, note = self._CONFIDENCE_RULES["action"]["not_registered"]
                    score += delta
                    notes.append(note)

            if isinstance(intent.params, dict):
                if intent.params:
                    delta, note = self._CONFIDENCE_RULES["action"]["params_present"]
                    score += delta
                    notes.append(note)
                else:
                    delta, note = self._CONFIDENCE_RULES["action"]["params_empty"]
                    score += delta
                    notes.append(note)
            else:
                delta, note = self._CONFIDENCE_RULES["action"]["params_not_object"]
                score += delta
                notes.append(note)

        thought = (intent.thought or "").strip()
        if len(thought) >= 8:
            delta, note = self._CONFIDENCE_RULES["thought"]["present"]
            score += delta
            notes.append(note)
        else:
            delta, note = self._CONFIDENCE_RULES["thought"]["too_short"]
            score += delta
            notes.append(note)

        plan = getattr(intent, "plan", None)
        if isinstance(plan, list) and plan:
            delta, note = self._CONFIDENCE_RULES["plan"]["present"]
            score += delta
            notes.append(note)

        # Keep score in [0, 1]
        score = max(0.0, min(1.0, score))
        return score, notes
