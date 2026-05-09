from typing import Optional, Dict, Any, List
from .base import IntentResolver
from .action_plan import ActionPlan
from services.llm.manager import LLMManager
from core.errors import AgentError, ErrorCode
import logging

logger = logging.getLogger("LLMResolver")

class LLMResolver(IntentResolver):
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
        scoped_allowed_actions = self._build_scoped_allowed_actions(context=context, session=session)
        if scoped_allowed_actions is not None:
            local_context["allowed_actions"] = scoped_allowed_actions
        discovery_primary = self._get_discovery_primary_action(session=session)
        
        try:
            intent = self.llm_manager.generate_intent(
                user_input,
                history,
                system_prompt,
                attachments=attachments,
                allowed_actions=scoped_allowed_actions,
                capability_registry=context.get("capability_registry"),
            )
            if not intent:
                return None
            
            # Fallback for missing action
            if not intent.action or not str(intent.action).strip():
                if intent.response_text or self._looks_like_conversational_turn(user_input):
                    logger.info("Empty action detected, defaulting to 'reply'.")
                    intent.action = "reply"

            # Semantic Validation
            if not intent.action or not str(intent.action).strip():
                raise ValueError("Provider returned an invalid action_id.")

            if intent.action == "reply" and not intent.response_text and not intent.thought:
                 raise ValueError("VALIDATION_ERROR: Empty 'reply' action. Provider must provide either 'response_text' or 'thought'.")

            if self._looks_like_conversational_turn(user_input) and intent.action != "reply":
                if intent.response_text:
                    logger.info("Forcing conversational turn to reply from action '%s'.", intent.action)
                    intent.action = "reply"

            if (
                discovery_primary
                and intent.action not in {"reply", "error", "system.control.consult_tools"}
                and scoped_allowed_actions
                and intent.action not in scoped_allowed_actions
            ):
                logger.info(
                    "Using discovered primary action '%s' instead of out-of-scope action '%s'.",
                    discovery_primary,
                    intent.action,
                )
                intent.action = discovery_primary

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

    @staticmethod
    def _looks_like_conversational_turn(user_input: str) -> bool:
        text = str(user_input or "").strip().lower()
        if not text:
            return False
        normalized = "".join(ch for ch in text if ch.isalnum() or ch.isspace()).strip()
        greetings = {
            "oi",
            "ola",
            "olá",
            "hello",
            "hi",
            "hey",
            "bom dia",
            "boa tarde",
            "boa noite",
            "e ai",
            "e aí",
        }
        if normalized in greetings:
            return True
        if len(normalized) <= 12 and any(g in normalized for g in ("oi", "olá", "ola", "hello", "hi", "hey")):
            return True
        return False

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
            else:
                has_attachments = isinstance(getattr(intent, "attachments", None), list) and len(intent.attachments) > 0
                if has_attachments:
                    score += 0.28
                    notes.append("reply_with_attachments_no_text")
                if has_attachments:
                    score += 0.28
                    notes.append("reply_with_attachments_no_text")
                elif intent.thought:
                    score += 0.15
                    notes.append("reply_with_thought_only")
                else:
                    score -= 0.20
                    notes.append("reply_without_text_or_thought")
        else:
            allowed_actions = context.get("allowed_actions")
            registry = context.get("capability_registry") or self.capability_registry
            discovery_primary = self._get_discovery_primary_action(context.get("session"))
            discovery_candidates = self._get_discovery_candidates(context.get("session"))

            if allowed_actions is not None:
                if action in allowed_actions:
                    score += 0.30
                    notes.append("action_allowed_for_principal")
                else:
                    score -= 0.35
                    notes.append("action_outside_allowed_scope")
            elif registry and hasattr(registry, "get_capability_for_action"):
                if registry.get_capability_for_action(action):
                    score += 0.25
                    notes.append("action_registered")
                else:
                    score -= 0.30
                    notes.append("action_not_registered")

            if discovery_candidates:
                if action == discovery_primary:
                    score += 0.18
                    notes.append("action_matches_discovery_primary")
                elif action in discovery_candidates:
                    score += 0.08
                    notes.append("action_matches_discovery_candidates")
                else:
                    score -= 0.15
                    notes.append("action_outside_discovery_scope")

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

    @staticmethod
    def _build_scoped_allowed_actions(context: Dict[str, Any], session: Any) -> Optional[List[str]]:
        base_allowed = context.get("allowed_actions")
        base_list = [str(x).strip() for x in base_allowed if str(x or "").strip()] if isinstance(base_allowed, (list, set, tuple)) else None

        session_state = getattr(session, "state_summary", {})
        discovery = session_state.get("last_tool_discovery") if isinstance(session_state, dict) else {}
        candidates = [
            str(x).strip()
            for x in (session_state.get("tool_candidates") or [])
            if str(x).strip()
        ]

        if not isinstance(discovery, dict) or not candidates:
            return list(base_list) if base_list is not None else base_allowed

        candidate_set = {x for x in candidates if x}
        if not candidate_set:
            return list(base_list) if base_list is not None else base_allowed

        always_allowed = ["system.control.consult_tools", "reply", "error"]
        scoped: List[str] = []
        base_pool = base_list if base_list is not None else list(candidate_set)

        for action_id in candidates:
            if action_id in base_pool and action_id not in scoped:
                scoped.append(action_id)
        for action_id in always_allowed:
            if action_id in base_pool and action_id not in scoped:
                scoped.append(action_id)

        if not scoped:
            scoped = [action_id for action_id in candidates if action_id in candidate_set]

        # Keep the discovery action available so the agent can re-query if the
        # discovered candidate set becomes stale.
        for action_id in always_allowed:
            if action_id not in scoped:
                scoped.append(action_id)
        return scoped

    @staticmethod
    def _get_discovery_primary_action(session: Any) -> Optional[str]:
        session_state = getattr(session, "state_summary", {})
        if not isinstance(session_state, dict):
            return None
        discovery = session_state.get("last_tool_discovery")
        if isinstance(discovery, dict):
            primary = str(discovery.get("primary_action_id") or "").strip()
            if primary:
                return primary
        candidates = [
            str(x).strip()
            for x in (session_state.get("tool_candidates") or [])
            if str(x).strip()
        ]
        return candidates[0] if candidates else None

    @staticmethod
    def _get_discovery_candidates(session: Any) -> List[str]:
        session_state = getattr(session, "state_summary", {})
        if not isinstance(session_state, dict):
            return []
        return [
            str(x).strip()
            for x in (session_state.get("tool_candidates") or [])
            if str(x).strip()
        ]
