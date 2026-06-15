import logging
from typing import Any, Dict, List
from ..base import CapabilityBase
from services.notifications.preference_parser import PreferenceParser

logger = logging.getLogger("NotificationCapability")

class NotificationCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "notifications"

    @property
    def name(self) -> str:
        return "notifications"

    @property
    def actions(self) -> List[str]:
        return [
            "send",
            "list_targets",
            "set_preference",
            "list_preferences",
            "record_feedback",
            "list_signal_assessments",
            "list_policy_suggestions",
            "review_policy_suggestion",
            "list_policy_patch_queue",
            "set_policy_patch_status",
            "explain_policy_decision",
            "apply_policy_patch_candidate",
            "list_applied_policy_patches",
            "rollback_applied_policy_patch",
        ]

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        # Phase 4: natural-language preference capture must go through the agent flow,
        # not reflex dispatch. Keep this disabled until a dedicated command surface exists.
        return []

    @staticmethod
    def _handle_preference_reflex(match) -> Dict[str, Any]:
        return {
            "preference_text": str(match.group(0) or "").strip(),
            "source": "explicit_user_command",
        }

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        if action_id == "notifications.send" or action_id == "send":
            return self.handle_send(params, context)
        elif action_id == "notifications.list_targets" or action_id == "list_targets":
            return self.handle_list_targets(params, context)
        elif action_id == "notifications.set_preference" or action_id == "set_preference":
            return self.handle_set_preference(params, context)
        elif action_id == "notifications.list_preferences" or action_id == "list_preferences":
            return self.handle_list_preferences(params, context)
        elif action_id == "notifications.record_feedback" or action_id == "record_feedback":
            return self.handle_record_feedback(params, context)
        elif action_id == "notifications.list_signal_assessments" or action_id == "list_signal_assessments":
            return self.handle_list_signal_assessments(params, context)
        elif action_id == "notifications.list_policy_suggestions" or action_id == "list_policy_suggestions":
            return self.handle_list_policy_suggestions(params, context)
        elif action_id == "notifications.review_policy_suggestion" or action_id == "review_policy_suggestion":
            return self.handle_review_policy_suggestion(params, context)
        elif action_id == "notifications.list_policy_patch_queue" or action_id == "list_policy_patch_queue":
            return self.handle_list_policy_patch_queue(params, context)
        elif action_id == "notifications.set_policy_patch_status" or action_id == "set_policy_patch_status":
            return self.handle_set_policy_patch_status(params, context)
        elif action_id == "notifications.explain_policy_decision" or action_id == "explain_policy_decision":
            return self.handle_explain_policy_decision(params, context)
        elif action_id == "notifications.apply_policy_patch_candidate" or action_id == "apply_policy_patch_candidate":
            return self.handle_apply_policy_patch_candidate(params, context)
        elif action_id == "notifications.list_applied_policy_patches" or action_id == "list_applied_policy_patches":
            return self.handle_list_applied_policy_patches(params, context)
        elif action_id == "notifications.rollback_applied_policy_patch" or action_id == "rollback_applied_policy_patch":
            return self.handle_rollback_applied_policy_patch(params, context)
        return self._envelope(
            status="failed",
            success=False,
            result_summary=f"Unknown action: {action_id}",
            structured_result={"action": action_id, "prepared": [], "sent": [], "confirmed": [], "failed": [action_id]},
            reason="UNKNOWN_ACTION",
            diagnostics={"capability": "notifications", "action": action_id},
        )

    def _resolve_orchestrator(self):
        return getattr(self, "orchestrator", None) or getattr(self.kernel, "orchestrator", None)

    def _resolve_target_user_id(self, params: Dict[str, Any], orchestrator) -> str:
        target_user_id = params.get("target_user_id")
        if target_user_id:
            return str(target_user_id)
        active_session = orchestrator.get_active_session(interface="all") if hasattr(orchestrator, "get_active_session") else None
        if active_session and getattr(active_session, "session_type", "") == "user":
            return str(getattr(active_session, "user_id", None) or getattr(active_session, "session_id", None))
        if hasattr(orchestrator, "sessions_index"):
            user_sessions = orchestrator.sessions_index.list_sessions(interface="all", session_type="user")
            if user_sessions:
                return str(user_sessions[0].get("user_id") or user_sessions[0].get("session_id") or "default")
        return "default"

    @staticmethod
    def _envelope(
        *,
        status: str,
        success: bool,
        result_summary: str,
        structured_result: Dict[str, Any],
        reason: str | None = None,
        attachment_delivery: Dict[str, Any] | None = None,
        diagnostics: Dict[str, Any] | None = None,
        freshness: Dict[str, Any] | None = None,
        requires_followup: bool = False,
        next_step_context: Dict[str, Any] | None = None,
        artifacts: List[Dict[str, Any]] | None = None,
        truncated: bool = False,
    ) -> Dict[str, Any]:
        return {
            "ok": bool(success),
            "success": bool(success),
            "status": status,
            "reason": reason,
            "result_summary": str(result_summary or "").strip(),
            "structured_result": structured_result,
            "attachment_delivery": attachment_delivery or {"requested": [], "resolved": [], "prepared": [], "sent": [], "confirmed": [], "errors": [], "status": "none"},
            "diagnostics": diagnostics or {},
            "freshness": freshness or {"source": "unknown", "resolved_at": None, "stale": False, "ttl_seconds": None},
            "requires_followup": bool(requires_followup),
            "next_step_context": next_step_context or {},
            "artifacts": artifacts or [],
            "truncated": bool(truncated),
        }

    def handle_send(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler for notifications.send action.
        """
        message = params.get("message")
        title = params.get("title")
        priority = params.get("priority", "medium")
        domain = params.get("domain", "system")
        delivery_mode = params.get("delivery_mode", "active_session_preferred")
        metadata = params.get("metadata") if isinstance(params.get("metadata"), dict) else {}
        as_agent_message = bool(params.get("as_agent_message", False))
        message_context = params.get("message_context") if isinstance(params.get("message_context"), dict) else {}

        if as_agent_message:
            # Agentic mode: keep payload structured until it reaches the target session.
            # The final wording should be produced by the session LLM (with user identity/persona),
            # not by this capability layer.
            metadata = {
                **metadata,
                "route_via_session_llm": True,
                "notification_goal": "notify_user",
                "suppress_legacy_prefix": True,
            }
            if not params.get("delivery_mode"):
                delivery_mode = "session_only"

        if not message:
            return {
                "ok": False,
                "success": False,
                "status": "error",
                "error": "MISSING_MESSAGE",
                "reason": "MISSING_MESSAGE",
                "result_summary": "Missing message parameter.",
                "structured_result": {"action": "notifications.send"},
                "artifacts": [],
                "attachment_delivery": {"status": "none", "confirmed": False},
                "freshness": {"status": "current", "source": "notifications"},
                "truncated": False,
                "requires_followup": False,
                "next_step_context": {},
                "diagnostics": {"capability": "notifications", "parse_status": "missing_message"},
            }

        target_session_id = params.get("target_id") or params.get("target_session_id")
        orchestrator = self._resolve_orchestrator()
        
        if not orchestrator:
            logger.warning("Orchestrator not found in NotificationCapability.")
            return {
                "ok": False,
                "success": False,
                "status": "error",
                "error": "ORCHESTRATOR_UNAVAILABLE",
                "reason": "ORCHESTRATOR_UNAVAILABLE",
                "result_summary": "Orchestrator not initialized.",
                "structured_result": {"action": "notifications.send"},
                "artifacts": [],
                "attachment_delivery": {"status": "none", "confirmed": False},
                "freshness": {"status": "current", "source": "notifications"},
                "truncated": False,
                "requires_followup": False,
                "next_step_context": {},
                "diagnostics": {"capability": "notifications", "parse_status": "orchestrator_unavailable"},
            }

        try:
            # We use notify_user on orchestrator which delegates to Dispatcher
            # We can pass more context if needed. In a truly agentic flow,
            # we might want to bypass the simple notify_user and speak to dispatcher directly,
            # but notify_user is a good entry point.
            
            target_user_id = self._resolve_target_user_id(params, orchestrator)

            # Create a localized intent if target_id is provided
            from services.notifications.models import NotificationIntent, NotificationPriority, DeliveryMode
            
            intent = NotificationIntent(
                source_domain=domain,
                target_user_id=target_user_id,
                message=message,
                title=title,
                priority=NotificationPriority(priority),
                delivery_mode=DeliveryMode(delivery_mode),
                target_session_id=target_session_id,
                metadata={**metadata, **message_context}
            )
            
            success = orchestrator.notification_dispatcher.dispatch(intent)
        except Exception as e:
            logger.error(f"Error in notifications capability: {e}")
            return {
                "ok": False,
                "success": False,
                "status": "error",
                "error": "NOTIFICATION_DISPATCH_FAILED",
                "reason": "NOTIFICATION_DISPATCH_FAILED",
                "result_summary": str(e),
                "structured_result": {"action": "notifications.send"},
                "artifacts": [],
                "attachment_delivery": {"status": "none", "confirmed": False},
                "freshness": {"status": "current", "source": "notifications"},
                "truncated": False,
                "requires_followup": False,
                "next_step_context": {},
                "diagnostics": {"capability": "notifications", "parse_status": "dispatch_failed"},
            }

        return {
            "ok": success,
            "success": success,
            "status": "success" if success else "failed",
            "reason": None if success else "NOTIFICATION_DISPATCH_FAILED",
            "result_summary": "Notification dispatched to delivery layer." if success else "Failed to dispatch notification.",
            "structured_result": {
                "channel": str(delivery_mode),
                "requested": [message] if message else [],
                "prepared": [message] if message else [],
                "sent": [message] if success else [],
                "confirmed": [message] if success else [],
                "failed": [] if success else [message],
                "action": "notifications.send",
                "target_session_id": target_session_id,
                "target_user_id": target_user_id,
                "delivery_mode": delivery_mode,
                "as_agent_message": as_agent_message,
                "metadata": {**metadata, **message_context},
            },
            "artifacts": [],
            "attachment_delivery": {
                "requested": [message] if message else [],
                "resolved": [target_session_id] if target_session_id else [],
                "prepared": [message] if message else [],
                "sent": [message] if success else [],
                "confirmed": [message] if success else [],
                "failed": [] if success else [message],
                "errors": [] if success else ["NOTIFICATION_DISPATCH_FAILED"],
                "status": "confirmed" if success else "failed",
            },
            "freshness": {"status": "current", "source": "notifications"},
            "truncated": False,
            "requires_followup": False,
            "next_step_context": {},
            "diagnostics": {"capability": "notifications", "dispatch_success": bool(success)},
            "details": "Notification dispatched to delivery layer." if success else "Failed to dispatch notification."
        }

    def _render_agent_notification_message(self, params: Dict[str, Any], context: Dict[str, Any]) -> str:
        orchestrator = getattr(self, "orchestrator", None) or getattr(self.kernel, "orchestrator", None)
        llm_manager = getattr(orchestrator, "llm_manager", None) if orchestrator else None
        message_context = params.get("message_context") if isinstance(params.get("message_context"), dict) else {}
        fallback_title = message_context.get("title") or params.get("title") or "evento"
        fallback = f"Senhor Lucas, lembrete: seu evento '{fallback_title}' está começando agora."

        if not llm_manager:
            return fallback

        try:
            payload = {
                "domain": params.get("domain", "system"),
                "priority": params.get("priority", "medium"),
                "context": message_context,
                "base_message": params.get("message") or "",
                "instruction": "Escreva apenas UMA frase curta de aviso ao usuário, em tom formal de assistente, sem mencionar loop/etapas/ações internas."
            }
            prompt = (
                "Gere uma mensagem de notificação para o usuário com base no JSON abaixo.\n"
                f"{payload}\n"
                "Regras: português, objetivo, sem markdown, sem metadados técnicos."
            )
            text = llm_manager.generate_text(
                prompt=prompt,
                system_prompt="Você é um assistente pessoal formal.",
                max_tokens=90,
                temperature=0.3,
            )
            text = str(text or "").strip()
            if not text:
                return fallback
            return text
        except Exception as e:
            logger.debug(f"Notification persona render fallback due to error: {e}")
            return fallback

    def handle_list_targets(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Lists available delivery targets (active sessions and push channels).
        """
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not orchestrator.notification_dispatcher:
            return self._envelope(
                status="failed",
                success=False,
                result_summary="Notification system not initialized.",
                structured_result={"action": "list_targets", "targets": []},
                reason="NOTIFICATION_SYSTEM_UNINITIALIZED",
                diagnostics={"capability": "notifications", "action": "list_targets"},
            )
            
        dispatcher = orchestrator.notification_dispatcher
        context_service = getattr(dispatcher.resolver, "context_service", None)
        if not context_service:
            return self._envelope(
                status="failed",
                success=False,
                result_summary="Context service unavailable.",
                structured_result={"action": "list_targets", "targets": []},
                reason="CONTEXT_SERVICE_UNAVAILABLE",
                diagnostics={"capability": "notifications", "action": "list_targets"},
            )
        
        user_id = params.get("user_id", "default")
        
        active_sessions = context_service.list_active_sessions(user_id)
        push_channels = context_service.list_push_channels(user_id)
        
        targets = []
        for s in active_sessions:
            targets.append({
                "id": s["session_id"],
                "type": "session",
                "interface": s.get("interface", "web"),
                "is_active": s.get("has_active_connection", False),
                "description": f"Session {s['session_id']} ({s.get('interface', 'web')})"
            })
            
        for c in push_channels:
            targets.append({
                "id": c.get("id", c["interface"]),
                "type": "push",
                "interface": c["interface"],
                "is_active": True,
                "description": f"Push channel: {c['interface']}"
            })
            
        return self._envelope(
            status="success" if targets else "partial",
            success=True,
            result_summary="Delivery targets listed." if targets else "No delivery targets found.",
            structured_result={"action": "list_targets", "requested": [], "prepared": [], "sent": [], "confirmed": targets, "failed": [], "targets": targets},
            reason=None if targets else "NO_TARGETS_FOUND",
            requires_followup=not bool(targets),
            next_step_context={"suggestion": "Set a target_session_id or target_user_id."} if not targets else {},
            diagnostics={"capability": "notifications", "action": "list_targets", "count": len(targets)},
        )

    def handle_set_preference(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "set_preference"}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "set_preference"})

        dispatcher = orchestrator.notification_dispatcher
        pref_store = getattr(dispatcher, "preference_store", None)
        if not pref_store:
            return self._envelope(status="failed", success=False, result_summary="UserPreferenceStore unavailable.", structured_result={"action": "set_preference"}, reason="PREFERENCE_STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "set_preference"})

        target_user_id = self._resolve_target_user_id(params, orchestrator)
        raw_text = str(
            params.get("preference_text")
            or params.get("text")
            or context.get("user_input")
            or ""
        ).strip()

        parsed = None
        if params.get("dimension") and params.get("key"):
            parsed = {
                "dimension": str(params.get("dimension")).strip().lower(),
                "key": str(params.get("key")).strip().lower(),
                "value": params.get("value"),
                "scope": params.get("scope") if isinstance(params.get("scope"), dict) else {"type": str(params.get("scope") or "global")},
                "priority": str(params.get("priority") or "hard").strip().lower(),
                "source": str(params.get("source") or "explicit_user_command").strip().lower(),
                "impact_level": str(params.get("impact_level") or "low").strip().lower(),
                "raw_text": raw_text,
            }
        else:
            parsed = PreferenceParser.parse(raw_text)

        if not parsed:
            return self._envelope(status="blocked", success=False, result_summary="Could not parse a supported explicit preference command.", structured_result={"action": "set_preference", "parsed": None}, reason="NOT_UNDERSTOOD", requires_followup=True, diagnostics={"capability": "notifications", "action": "set_preference", "parse_status": "not_understood"})

        impact = str(parsed.get("impact_level") or "low").strip().lower()
        confirmed = bool(params.get("confirmed", False))
        if impact in {"medium", "high"} and not confirmed:
            return self._envelope(status="partial", success=False, result_summary="Confirmation required before applying preference.", structured_result={"action": "set_preference", "prepared": [parsed], "confirmed": [], "failed": []}, reason="CONFIRMATION_REQUIRED", requires_followup=True, next_step_context={"question": "Confirma aplicar esta preferência de notificação?", "proposed_preference": parsed, "impact_level": impact}, diagnostics={"capability": "notifications", "action": "set_preference", "impact_level": impact})

        record = pref_store.upsert_preference(
            user_id=target_user_id,
            dimension=str(parsed.get("dimension") or ""),
            key=str(parsed.get("key") or ""),
            value=parsed.get("value"),
            scope=parsed.get("scope") if isinstance(parsed.get("scope"), dict) else {"type": "global"},
            priority=str(parsed.get("priority") or "hard"),
            source=str(parsed.get("source") or "explicit_user_command"),
            impact_level=impact,
        )
        return self._envelope(status="success", success=True, result_summary="Preference updated.", structured_result={"action": "set_preference", "prepared": [parsed], "confirmed": [record], "failed": [], "preference": record, "preference_version": pref_store.get_user_preference_version(target_user_id), "global_preference_version": pref_store.get_global_preference_version(), "source": "explicit_user_command"}, diagnostics={"capability": "notifications", "action": "set_preference", "confirmed": True})

    def handle_list_preferences(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "list_preferences", "preferences": []}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "list_preferences"})

        dispatcher = orchestrator.notification_dispatcher
        pref_store = getattr(dispatcher, "preference_store", None)
        if not pref_store:
            return self._envelope(status="failed", success=False, result_summary="UserPreferenceStore unavailable.", structured_result={"action": "list_preferences", "preferences": []}, reason="PREFERENCE_STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "list_preferences"})

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator))
        dimension = str(params.get("dimension") or "").strip().lower() or None
        prefs = pref_store.list_preferences(
            user_id=target_user_id,
            dimension=dimension,
            active_only=bool(params.get("active_only", True)),
        )
        return self._envelope(status="success" if prefs else "partial", success=True, result_summary="Preferences listed." if prefs else "No preferences found.", structured_result={"action": "list_preferences", "confirmed": bool(prefs), "prepared": [], "sent": [], "confirmed_items": prefs, "failed": [], "count": len(prefs), "preferences": prefs, "preference_version": pref_store.get_user_preference_version(target_user_id), "global_preference_version": pref_store.get_global_preference_version()}, reason=None if prefs else "NO_PREFERENCES_FOUND", requires_followup=not bool(prefs), diagnostics={"capability": "notifications", "action": "list_preferences"})

    def handle_record_feedback(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "record_feedback"}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "record_feedback"})
        dispatcher = orchestrator.notification_dispatcher
        target_user_id = self._resolve_target_user_id(params, orchestrator)

        signal_name = str(params.get("signal_name") or "").strip().lower()
        if not signal_name:
            return self._envelope(status="blocked", success=False, result_summary="Missing signal_name.", structured_result={"action": "record_feedback"}, reason="MISSING_SIGNAL_NAME", requires_followup=True, diagnostics={"capability": "notifications", "action": "record_feedback"})

        signal_type = str(params.get("signal_type") or "explicit").strip().lower()
        value = params.get("value", True)
        source = str(params.get("source") or "user_feedback").strip().lower()
        source_domain = str(params.get("source_domain") or "notifications").strip().lower()
        intent_id = params.get("intent_id")
        signal_context = params.get("context") if isinstance(params.get("context"), dict) else {}

        recorded = dispatcher.record_feedback_signal(
            user_id=target_user_id,
            signal_name=signal_name,
            value=value,
            signal_type=signal_type,
            source=source,
            context=signal_context,
            source_domain=source_domain,
            intent_id=intent_id,
        )
        return self._envelope(status="success", success=True, result_summary="Feedback recorded.", structured_result={"action": "record_feedback", "prepared": [], "sent": [], "confirmed": [recorded], "failed": [], "recorded": recorded}, diagnostics={"capability": "notifications", "action": "record_feedback"})

    def handle_list_signal_assessments(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "list_signal_assessments", "assessments": []}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "list_signal_assessments"})
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return self._envelope(status="failed", success=False, result_summary="NotificationStore unavailable.", structured_result={"action": "list_signal_assessments", "assessments": []}, reason="STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "list_signal_assessments"})

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator))
        signal_name = str(params.get("signal_name") or "").strip().lower() or None
        limit = int(params.get("limit", 50) or 50)
        assessments = store.list_signal_assessments(
            user_id=target_user_id,
            signal_name=signal_name,
            limit=max(1, min(500, limit)),
        )
        return self._envelope(status="success" if assessments else "partial", success=True, result_summary="Signal assessments listed." if assessments else "No signal assessments found.", structured_result={"action": "list_signal_assessments", "prepared": [], "sent": [], "confirmed": assessments, "failed": [], "count": len(assessments), "assessments": assessments}, reason=None if assessments else "NO_ASSESSMENTS_FOUND", requires_followup=not bool(assessments), diagnostics={"capability": "notifications", "action": "list_signal_assessments"})

    def handle_list_policy_suggestions(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "list_policy_suggestions", "suggestions": []}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "list_policy_suggestions"})
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return self._envelope(status="failed", success=False, result_summary="NotificationStore unavailable.", structured_result={"action": "list_policy_suggestions", "suggestions": []}, reason="STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "list_policy_suggestions"})

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator))
        status = str(params.get("status") or "").strip().lower() or None
        limit = int(params.get("limit", 50) or 50)
        suggestions = store.list_policy_suggestions(
            user_id=target_user_id,
            status=status,
            limit=max(1, min(500, limit)),
        )
        return self._envelope(status="success" if suggestions else "partial", success=True, result_summary="Policy suggestions listed." if suggestions else "No policy suggestions found.", structured_result={"action": "list_policy_suggestions", "prepared": [], "sent": [], "confirmed": suggestions, "failed": [], "count": len(suggestions), "suggestions": suggestions, "mode": "observe_only_no_auto_patch"}, reason=None if suggestions else "NO_SUGGESTIONS_FOUND", requires_followup=not bool(suggestions), diagnostics={"capability": "notifications", "action": "list_policy_suggestions"})

    def handle_review_policy_suggestion(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "review_policy_suggestion"}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "review_policy_suggestion"})
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return self._envelope(status="failed", success=False, result_summary="NotificationStore unavailable.", structured_result={"action": "review_policy_suggestion"}, reason="STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "review_policy_suggestion"})

        suggestion_id = str(params.get("suggestion_id") or "").strip()
        decision = str(params.get("decision") or "").strip().lower()
        if not suggestion_id:
            return self._envelope(status="blocked", success=False, result_summary="Missing suggestion_id.", structured_result={"action": "review_policy_suggestion"}, reason="MISSING_SUGGESTION_ID", requires_followup=True, diagnostics={"capability": "notifications", "action": "review_policy_suggestion"})
        if decision not in {"approved", "rejected"}:
            return self._envelope(status="blocked", success=False, result_summary="decision must be approved or rejected.", structured_result={"action": "review_policy_suggestion"}, reason="INVALID_DECISION", requires_followup=True, diagnostics={"capability": "notifications", "action": "review_policy_suggestion"})

        reviewer = str(params.get("reviewed_by") or "user")
        reason = str(params.get("reason") or "").strip()
        updated = store.review_policy_suggestion(
            suggestion_id=suggestion_id,
            decision=decision,
            reviewer=reviewer,
            reason=reason,
        )
        if not updated:
            return self._envelope(status="partial", success=False, result_summary="Policy suggestion not found.", structured_result={"action": "review_policy_suggestion"}, reason="POLICY_SUGGESTION_NOT_FOUND", requires_followup=True, diagnostics={"capability": "notifications", "action": "review_policy_suggestion"})
        return self._envelope(status="success", success=True, result_summary="Policy suggestion reviewed.", structured_result={"action": "review_policy_suggestion", "prepared": [], "sent": [], "confirmed": [updated], "failed": [], "suggestion": updated, "note": "Decision recorded. No automatic policy patch is applied in observe-only mode."}, diagnostics={"capability": "notifications", "action": "review_policy_suggestion"})

    def handle_list_policy_patch_queue(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "list_policy_patch_queue"}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "list_policy_patch_queue"})
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return self._envelope(status="failed", success=False, result_summary="NotificationStore unavailable.", structured_result={"action": "list_policy_patch_queue"}, reason="STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "list_policy_patch_queue"})

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator))
        status = str(params.get("status") or "").strip().lower() or None
        limit = int(params.get("limit", 50) or 50)
        queue = store.list_policy_patch_candidates(
            user_id=target_user_id,
            status=status,
            limit=max(1, min(500, limit)),
        )
        return self._envelope(status="success" if queue else "partial", success=True, result_summary="Policy patch queue listed." if queue else "No policy patch candidates found.", structured_result={"action": "list_policy_patch_queue", "prepared": [], "sent": [], "confirmed": queue, "failed": [], "count": len(queue), "patch_queue": queue, "mode": "manual_only"}, reason=None if queue else "NO_PATCH_CANDIDATES_FOUND", requires_followup=not bool(queue), diagnostics={"capability": "notifications", "action": "list_policy_patch_queue"})

    def handle_set_policy_patch_status(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "set_policy_patch_status"}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "set_policy_patch_status"})
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return self._envelope(status="failed", success=False, result_summary="NotificationStore unavailable.", structured_result={"action": "set_policy_patch_status"}, reason="STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "set_policy_patch_status"})

        patch_id = str(params.get("patch_id") or "").strip()
        status = str(params.get("status") or "").strip().lower()
        if not patch_id:
            return self._envelope(status="blocked", success=False, result_summary="Missing patch_id.", structured_result={"action": "set_policy_patch_status"}, reason="MISSING_PATCH_ID", requires_followup=True, diagnostics={"capability": "notifications", "action": "set_policy_patch_status"})
        if status not in {"pending", "approved_for_apply", "rejected", "applied_manual"}:
            return self._envelope(status="blocked", success=False, result_summary="Invalid status.", structured_result={"action": "set_policy_patch_status"}, reason="INVALID_STATUS", requires_followup=True, diagnostics={"capability": "notifications", "action": "set_policy_patch_status"})

        reason = str(params.get("reason") or "").strip()
        reviewer = str(params.get("reviewed_by") or "user")
        updated = store.set_policy_patch_candidate_status(
            patch_id=patch_id,
            status=status,
            reviewer=reviewer,
            reason=reason,
        )
        if not updated:
            return self._envelope(status="partial", success=False, result_summary="Patch candidate not found.", structured_result={"action": "set_policy_patch_status"}, reason="PATCH_CANDIDATE_NOT_FOUND", requires_followup=True, diagnostics={"capability": "notifications", "action": "set_policy_patch_status"})
        return self._envelope(status="success", success=True, result_summary="Policy patch status updated.", structured_result={"action": "set_policy_patch_status", "prepared": [], "sent": [], "confirmed": [updated], "failed": [], "patch_candidate": updated, "note": "Status atualizado. Aplicação de patch continua manual (sem auto-apply)."}, diagnostics={"capability": "notifications", "action": "set_policy_patch_status"})

    def handle_explain_policy_decision(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "explain_policy_decision"}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "explain_policy_decision"})
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return self._envelope(status="failed", success=False, result_summary="NotificationStore unavailable.", structured_result={"action": "explain_policy_decision"}, reason="STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "explain_policy_decision"})

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator)).strip()
        decision_id = str(params.get("decision_id") or "").strip()
        signal_id = str(params.get("signal_id") or "").strip()
        assessment_id = str(params.get("assessment_id") or "").strip()
        suggestion_id = str(params.get("suggestion_id") or "").strip()
        patch_id = str(params.get("patch_id") or "").strip()

        # Resolve linked records
        suggestion = store.get_policy_suggestion(suggestion_id) if suggestion_id else None
        patch = store.get_policy_patch_candidate(patch_id) if patch_id else None
        assessment = store.get_signal_assessment(assessment_id) if assessment_id else None
        signal = store.get_learning_signal(signal_id) if signal_id else None

        if patch and not suggestion:
            suggestion = store.get_policy_suggestion(str(patch.get("source_suggestion_id") or ""))
        if suggestion and not assessment:
            assessment = store.get_signal_assessment(str(suggestion.get("assessment_id") or ""))
        if suggestion and not signal:
            signal = store.get_learning_signal(str(suggestion.get("signal_id") or ""))
        if assessment and not signal:
            signal = store.get_learning_signal(str(assessment.get("signal_id") or ""))

        decision_trace = None
        if decision_id:
            traces = store.list_decision_traces(user_id=target_user_id, limit=500)
            decision_trace = next((t for t in traces if str(t.get("decision_id") or "").strip() == decision_id), None)
        if not decision_trace:
            traces = store.list_decision_traces(user_id=target_user_id, limit=200)
            if suggestion:
                pver = suggestion.get("policy_version")
                prefv = suggestion.get("preference_version")
                decision_trace = next(
                    (
                        t for t in traces
                        if (pver is None or t.get("policy_version") == pver)
                        and (prefv is None or t.get("preference_version") == prefv)
                    ),
                    None,
                )
            elif traces:
                decision_trace = traces[0]

        if not any([decision_trace, signal, assessment, suggestion, patch]):
            return self._envelope(status="partial", success=False, result_summary="No matching decision artifacts found.", structured_result={"action": "explain_policy_decision"}, reason="NOT_FOUND", requires_followup=True, diagnostics={"capability": "notifications", "action": "explain_policy_decision"})

        lines = []
        if suggestion:
            lines.append(
                f"Sugestão {suggestion.get('suggestion_id')} foi gerada para '{suggestion.get('target')}' "
                f"com confiança {float(suggestion.get('confidence_score') or 0.0):.2f}."
            )
            lines.append(f"Status da sugestão: {suggestion.get('status')}.")
        if patch:
            lines.append(
                f"Patch candidate {patch.get('patch_id')} está em status '{patch.get('status')}' "
                f"(manual_only, apply_ready={bool(patch.get('apply_ready'))})."
            )
        if assessment:
            lines.append(
                f"Assessment {assessment.get('assessment_id')} classificou o sinal como "
                f"{assessment.get('reliability_flag')} (confidence={float(assessment.get('confidence_score') or 0.0):.2f})."
            )
        if signal:
            lines.append(
                f"Sinal base: '{signal.get('signal_name')}' ({signal.get('signal_type')}) "
                f"originado em '{signal.get('source_domain')}'."
            )
        if decision_trace:
            applied = decision_trace.get("applied_rules") if isinstance(decision_trace.get("applied_rules"), list) else []
            lines.append(
                f"Decision trace policy_version={decision_trace.get('policy_version')} "
                f"preference_version={decision_trace.get('preference_version')}."
            )
            if applied:
                lines.append(f"Regras aplicadas: {', '.join(str(x) for x in applied[:6])}.")

        explanation = " ".join(lines).strip()
        return self._envelope(status="success", success=True, result_summary="Policy decision explained.", structured_result={"action": "explain_policy_decision", "prepared": [], "sent": [], "confirmed": [], "failed": [], "explanation": explanation, "artifacts": {"decision_trace": decision_trace, "signal": signal, "assessment": assessment, "suggestion": suggestion, "patch_candidate": patch}}, diagnostics={"capability": "notifications", "action": "explain_policy_decision"})

    def handle_apply_policy_patch_candidate(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "apply_policy_patch_candidate"}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "apply_policy_patch_candidate"})
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return self._envelope(status="failed", success=False, result_summary="NotificationStore unavailable.", structured_result={"action": "apply_policy_patch_candidate"}, reason="STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "apply_policy_patch_candidate"})

        patch_id = str(params.get("patch_id") or "").strip()
        confirmed = bool(params.get("confirmed", False))
        if not patch_id:
            return self._envelope(status="blocked", success=False, result_summary="Missing patch_id.", structured_result={"action": "apply_policy_patch_candidate"}, reason="MISSING_PATCH_ID", requires_followup=True, diagnostics={"capability": "notifications", "action": "apply_policy_patch_candidate"})
        if not confirmed:
            return self._envelope(status="partial", success=False, result_summary="Dual gate: set confirmed=true to apply approved_for_apply patch candidate.", structured_result={"action": "apply_policy_patch_candidate"}, reason="CONFIRMATION_REQUIRED", requires_followup=True, diagnostics={"capability": "notifications", "action": "apply_policy_patch_candidate"})

        reviewer = str(params.get("applied_by") or params.get("reviewed_by") or "user")
        reason = str(params.get("reason") or "").strip()
        canary_enabled = bool(params.get("canary_enabled", False))
        canary_required_observations = int(params.get("canary_required_observations", 3) or 3)
        canary_max_failure_rate = float(params.get("canary_max_failure_rate", 0.34) or 0.34)
        result = store.apply_policy_patch_candidate(
            patch_id=patch_id,
            applied_by=reviewer,
            reason=reason,
            require_status="approved_for_apply",
            canary_enabled=canary_enabled,
            canary_required_observations=max(1, min(100, canary_required_observations)),
            canary_max_failure_rate=max(0.0, min(1.0, canary_max_failure_rate)),
        )
        if not bool(result.get("ok")):
            return self._envelope(status="failed", success=False, result_summary=str(result.get("error") or "apply_failed"), structured_result={"action": "apply_policy_patch_candidate"}, reason="APPLY_FAILED", diagnostics={"capability": "notifications", "action": "apply_policy_patch_candidate"})
        return self._envelope(status="success", success=True, result_summary="Policy patch applied.", structured_result={"action": "apply_policy_patch_candidate", "prepared": [], "sent": [], "confirmed": [result.get("applied_patch")], "failed": [], "applied_patch": result.get("applied_patch"), "mode": "manual_apply_guarded_canary" if canary_enabled else "manual_apply_guarded"}, diagnostics={"capability": "notifications", "action": "apply_policy_patch_candidate"})

    def handle_list_applied_policy_patches(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "list_applied_policy_patches"}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "list_applied_policy_patches"})
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return self._envelope(status="failed", success=False, result_summary="NotificationStore unavailable.", structured_result={"action": "list_applied_policy_patches"}, reason="STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "list_applied_policy_patches"})

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator))
        status = str(params.get("status") or "").strip().lower() or None
        limit = int(params.get("limit", 50) or 50)
        patches = store.list_applied_policy_patches(
            user_id=target_user_id,
            status=status,
            limit=max(1, min(500, limit)),
        )
        return self._envelope(status="success" if patches else "partial", success=True, result_summary="Applied policy patches listed." if patches else "No applied policy patches found.", structured_result={"action": "list_applied_policy_patches", "prepared": [], "sent": [], "confirmed": patches, "failed": [], "count": len(patches), "applied_patches": patches}, reason=None if patches else "NO_APPLIED_PATCHES_FOUND", requires_followup=not bool(patches), diagnostics={"capability": "notifications", "action": "list_applied_policy_patches"})

    def handle_rollback_applied_policy_patch(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return self._envelope(status="failed", success=False, result_summary="Notification system not initialized.", structured_result={"action": "rollback_applied_policy_patch"}, reason="NOTIFICATION_SYSTEM_UNINITIALIZED", diagnostics={"capability": "notifications", "action": "rollback_applied_policy_patch"})
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return self._envelope(status="failed", success=False, result_summary="NotificationStore unavailable.", structured_result={"action": "rollback_applied_policy_patch"}, reason="STORE_UNAVAILABLE", diagnostics={"capability": "notifications", "action": "rollback_applied_policy_patch"})

        applied_id = str(params.get("applied_id") or "").strip()
        if not applied_id:
            return self._envelope(status="blocked", success=False, result_summary="Missing applied_id.", structured_result={"action": "rollback_applied_policy_patch"}, reason="MISSING_APPLIED_ID", requires_followup=True, diagnostics={"capability": "notifications", "action": "rollback_applied_policy_patch"})
        reviewer = str(params.get("reviewed_by") or "user")
        reason = str(params.get("reason") or "").strip()
        result = store.rollback_applied_policy_patch(
            applied_id=applied_id,
            reviewer=reviewer,
            reason=reason,
            automatic=False,
        )
        if not bool(result.get("ok")):
            return self._envelope(status="failed", success=False, result_summary=str(result.get("error") or "rollback_failed"), structured_result={"action": "rollback_applied_policy_patch"}, reason="ROLLBACK_FAILED", diagnostics={"capability": "notifications", "action": "rollback_applied_policy_patch"})
        return self._envelope(status="success", success=True, result_summary="Applied policy patch rolled back.", structured_result={"action": "rollback_applied_policy_patch", "prepared": [], "sent": [], "confirmed": [result.get("applied_patch")], "failed": [], "applied_patch": result.get("applied_patch"), "mode": "manual_rollback"}, diagnostics={"capability": "notifications", "action": "rollback_applied_policy_patch"})
