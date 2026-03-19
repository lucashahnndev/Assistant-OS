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
        return [
            {
                "pattern": (
                    r"^(?:atlas[\s,:-]*)?"
                    r"(?:n[aã]o\s+(?:me\s+)?(?:mande|envie|dispare).*(?:push|notifica[cç][aã]o)"
                    r"|sem\s+push"
                    r"|me\s+avise\s+sempre\s+\d{1,3}\s*(?:min|mins|minutos?)\s*(?:antes)?"
                    r"|n[aã]o\s+me\s+interrompa\s+enquanto\s+estou\s+conversando"
                    r"|seja\s+mais\s+direto(?:\s+nas\s+mensagens)?"
                    r"|evite\s+mensagens\s+longas)$"
                ),
                "action_id": "notifications.set_preference",
                "handler": self._handle_preference_reflex,
            }
        ]

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
        return {"ok": False, "error": f"Unknown action: {action_id}"}

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
            return {"ok": False, "error": "Missing message parameter."}

        target_session_id = params.get("target_id") or params.get("target_session_id")
        orchestrator = self._resolve_orchestrator()
        
        if not orchestrator:
            logger.warning("Orchestrator not found in NotificationCapability.")
            return {"ok": False, "error": "Orchestrator not initialized."}

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
            return {"ok": False, "error": str(e)}

        return {
            "ok": success,
            "status": "sent" if success else "failed",
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
            return {"ok": False, "error": "Notification system not initialized."}
            
        dispatcher = orchestrator.notification_dispatcher
        context_service = getattr(dispatcher.resolver, "context_service", None)
        if not context_service:
            return {"ok": False, "error": "Context service unavailable."}
        
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
            
        return {
            "ok": True,
            "targets": targets
        }

    def handle_set_preference(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}

        dispatcher = orchestrator.notification_dispatcher
        pref_store = getattr(dispatcher, "preference_store", None)
        if not pref_store:
            return {"ok": False, "error": "UserPreferenceStore unavailable."}

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
            return {
                "ok": False,
                "status": "not_understood",
                "error": "Could not parse a supported explicit preference command.",
            }

        impact = str(parsed.get("impact_level") or "low").strip().lower()
        confirmed = bool(params.get("confirmed", False))
        if impact in {"medium", "high"} and not confirmed:
            return {
                "ok": False,
                "status": "confirmation_required",
                "data": {
                    "question": "Confirma aplicar esta preferência de notificação?",
                    "proposed_preference": parsed,
                    "impact_level": impact,
                },
            }

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
        return {
            "ok": True,
            "status": "success",
            "data": {
                "preference": record,
                "preference_version": pref_store.get_user_preference_version(target_user_id),
                "global_preference_version": pref_store.get_global_preference_version(),
                "source": "explicit_user_command",
            },
        }

    def handle_list_preferences(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}

        dispatcher = orchestrator.notification_dispatcher
        pref_store = getattr(dispatcher, "preference_store", None)
        if not pref_store:
            return {"ok": False, "error": "UserPreferenceStore unavailable."}

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator))
        dimension = str(params.get("dimension") or "").strip().lower() or None
        prefs = pref_store.list_preferences(
            user_id=target_user_id,
            dimension=dimension,
            active_only=bool(params.get("active_only", True)),
        )
        return {
            "ok": True,
            "status": "success",
            "data": {
                "count": len(prefs),
                "preferences": prefs,
                "preference_version": pref_store.get_user_preference_version(target_user_id),
                "global_preference_version": pref_store.get_global_preference_version(),
            },
        }

    def handle_record_feedback(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}
        dispatcher = orchestrator.notification_dispatcher
        target_user_id = self._resolve_target_user_id(params, orchestrator)

        signal_name = str(params.get("signal_name") or "").strip().lower()
        if not signal_name:
            return {"ok": False, "error": "Missing signal_name."}

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
        return {
            "ok": True,
            "status": "success",
            "data": recorded,
        }

    def handle_list_signal_assessments(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return {"ok": False, "error": "NotificationStore unavailable."}

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator))
        signal_name = str(params.get("signal_name") or "").strip().lower() or None
        limit = int(params.get("limit", 50) or 50)
        assessments = store.list_signal_assessments(
            user_id=target_user_id,
            signal_name=signal_name,
            limit=max(1, min(500, limit)),
        )
        return {
            "ok": True,
            "status": "success",
            "data": {
                "count": len(assessments),
                "assessments": assessments,
            },
        }

    def handle_list_policy_suggestions(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return {"ok": False, "error": "NotificationStore unavailable."}

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator))
        status = str(params.get("status") or "").strip().lower() or None
        limit = int(params.get("limit", 50) or 50)
        suggestions = store.list_policy_suggestions(
            user_id=target_user_id,
            status=status,
            limit=max(1, min(500, limit)),
        )
        return {
            "ok": True,
            "status": "success",
            "data": {
                "count": len(suggestions),
                "suggestions": suggestions,
                "mode": "observe_only_no_auto_patch",
            },
        }

    def handle_review_policy_suggestion(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return {"ok": False, "error": "NotificationStore unavailable."}

        suggestion_id = str(params.get("suggestion_id") or "").strip()
        decision = str(params.get("decision") or "").strip().lower()
        if not suggestion_id:
            return {"ok": False, "error": "Missing suggestion_id."}
        if decision not in {"approved", "rejected"}:
            return {"ok": False, "error": "decision must be approved or rejected."}

        reviewer = str(params.get("reviewed_by") or "user")
        reason = str(params.get("reason") or "").strip()
        updated = store.review_policy_suggestion(
            suggestion_id=suggestion_id,
            decision=decision,
            reviewer=reviewer,
            reason=reason,
        )
        if not updated:
            return {"ok": False, "status": "not_found", "error": "Policy suggestion not found."}
        return {
            "ok": True,
            "status": "success",
            "data": {
                "suggestion": updated,
                "note": "Decision recorded. No automatic policy patch is applied in observe-only mode.",
            },
        }

    def handle_list_policy_patch_queue(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return {"ok": False, "error": "NotificationStore unavailable."}

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator))
        status = str(params.get("status") or "").strip().lower() or None
        limit = int(params.get("limit", 50) or 50)
        queue = store.list_policy_patch_candidates(
            user_id=target_user_id,
            status=status,
            limit=max(1, min(500, limit)),
        )
        return {
            "ok": True,
            "status": "success",
            "data": {
                "count": len(queue),
                "patch_queue": queue,
                "mode": "manual_only",
            },
        }

    def handle_set_policy_patch_status(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return {"ok": False, "error": "NotificationStore unavailable."}

        patch_id = str(params.get("patch_id") or "").strip()
        status = str(params.get("status") or "").strip().lower()
        if not patch_id:
            return {"ok": False, "error": "Missing patch_id."}
        if status not in {"pending", "approved_for_apply", "rejected", "applied_manual"}:
            return {"ok": False, "error": "Invalid status."}

        reason = str(params.get("reason") or "").strip()
        reviewer = str(params.get("reviewed_by") or "user")
        updated = store.set_policy_patch_candidate_status(
            patch_id=patch_id,
            status=status,
            reviewer=reviewer,
            reason=reason,
        )
        if not updated:
            return {"ok": False, "status": "not_found", "error": "Patch candidate not found."}
        return {
            "ok": True,
            "status": "success",
            "data": {
                "patch_candidate": updated,
                "note": "Status atualizado. Aplicação de patch continua manual (sem auto-apply).",
            },
        }

    def handle_explain_policy_decision(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return {"ok": False, "error": "NotificationStore unavailable."}

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
            return {
                "ok": False,
                "status": "not_found",
                "error": "No matching decision artifacts found.",
            }

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
        return {
            "ok": True,
            "status": "success",
            "data": {
                "explanation": explanation,
                "artifacts": {
                    "decision_trace": decision_trace,
                    "signal": signal,
                    "assessment": assessment,
                    "suggestion": suggestion,
                    "patch_candidate": patch,
                },
            },
        }

    def handle_apply_policy_patch_candidate(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return {"ok": False, "error": "NotificationStore unavailable."}

        patch_id = str(params.get("patch_id") or "").strip()
        confirmed = bool(params.get("confirmed", False))
        if not patch_id:
            return {"ok": False, "error": "Missing patch_id."}
        if not confirmed:
            return {
                "ok": False,
                "status": "confirmation_required",
                "error": "Dual gate: set confirmed=true to apply approved_for_apply patch candidate.",
            }

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
            return {"ok": False, "status": "failed", "error": str(result.get("error") or "apply_failed")}
        return {
            "ok": True,
            "status": "success",
            "data": {
                "applied_patch": result.get("applied_patch"),
                "mode": "manual_apply_guarded_canary" if canary_enabled else "manual_apply_guarded",
            },
        }

    def handle_list_applied_policy_patches(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return {"ok": False, "error": "NotificationStore unavailable."}

        target_user_id = str(params.get("target_user_id") or self._resolve_target_user_id(params, orchestrator))
        status = str(params.get("status") or "").strip().lower() or None
        limit = int(params.get("limit", 50) or 50)
        patches = store.list_applied_policy_patches(
            user_id=target_user_id,
            status=status,
            limit=max(1, min(500, limit)),
        )
        return {
            "ok": True,
            "status": "success",
            "data": {
                "count": len(patches),
                "applied_patches": patches,
            },
        }

    def handle_rollback_applied_policy_patch(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        orchestrator = self._resolve_orchestrator()
        if not orchestrator or not getattr(orchestrator, "notification_dispatcher", None):
            return {"ok": False, "error": "Notification system not initialized."}
        dispatcher = orchestrator.notification_dispatcher
        store = getattr(dispatcher, "store", None)
        if not store:
            return {"ok": False, "error": "NotificationStore unavailable."}

        applied_id = str(params.get("applied_id") or "").strip()
        if not applied_id:
            return {"ok": False, "error": "Missing applied_id."}
        reviewer = str(params.get("reviewed_by") or "user")
        reason = str(params.get("reason") or "").strip()
        result = store.rollback_applied_policy_patch(
            applied_id=applied_id,
            reviewer=reviewer,
            reason=reason,
            automatic=False,
        )
        if not bool(result.get("ok")):
            return {"ok": False, "status": "failed", "error": str(result.get("error") or "rollback_failed")}
        return {
            "ok": True,
            "status": "success",
            "data": {
                "applied_patch": result.get("applied_patch"),
                "mode": "manual_rollback",
            },
        }
