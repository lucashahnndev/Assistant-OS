import logging
from typing import Optional, Dict, Any
import time
import uuid
from .models import NotificationIntent, NotificationPriority
from .delivery_resolver import DeliveryResolver
from .alert_policy_engine import AlertPolicyEngine
from .user_preferences import UserPreferenceStore
from .signal_confidence_engine import SignalConfidenceEngine
from services.agent_events.models import AgentEvent

logger = logging.getLogger("NotificationDispatcher")

class NotificationDispatcher:
    def __init__(self, kernel, resolver, store):
        self.kernel = kernel
        self.resolver = resolver
        self.store = store
        self.preference_store = UserPreferenceStore(getattr(store, "data_dir", "data"))
        self.policy_engine = AlertPolicyEngine(self.preference_store, notification_store=store)
        self.signal_confidence_engine = SignalConfidenceEngine()
        self._recent_fingerprints = {}
        self._dedupe_ttl_sec = 20.0

    def dispatch(self, intent: NotificationIntent):
        """
        Entry point for dispatching a notification intent.
        """
        logger.info(f"Dispatching intent {intent.intent_id} from {intent.source_domain}")

        fp = self._fingerprint(intent)
        now = time.time()
        self._prune_fingerprints(now)
        if fp in self._recent_fingerprints and (now - self._recent_fingerprints[fp]) <= self._dedupe_ttl_sec:
            logger.info("Skipping duplicate notification within dedupe window | fp=%s", fp)
            self._record_signal(
                intent=intent,
                signal_type="implicit",
                signal_name="duplicate_suppressed",
                value=True,
                context={"dedupe_fingerprint": fp},
                source="system_observer",
            )
            return True
        self._recent_fingerprints[fp] = now

        # Phase-0 policy application:
        # explicit user preferences override adaptive behavior.
        decision_trace: Dict[str, Any] = {}
        try:
            intent, decision_trace = self.policy_engine.apply(intent)
            self.store.add_decision_trace(decision_trace)
        except Exception as e:
            logger.error("AlertPolicyEngine.apply failed for %s: %s", intent.intent_id, e)
        
        targets = self.resolver.resolve(intent)
        
        if not targets:
            logger.info(f"No active targets found for {intent.target_user_id}. Storing as pending.")
            self.store.add_pending(intent)
            md = intent.metadata if isinstance(intent.metadata, dict) else {}
            signal_name = "deferred_by_interruptibility" if bool(md.get("queue_if_active_conversation")) else "queued_no_target"
            self._record_signal(
                intent=intent,
                signal_type="contextual",
                signal_name=signal_name,
                value=True,
                context={"target_count": 0},
                source="system_observer",
            )
            return False
            
        success_count = 0
        for target in targets:
            success = False
            if target.target_type == "session":
                success = self._send_to_session(target.target_id, intent)
            elif target.target_type == "push":
                success = self._send_to_push(target.interface, intent)
            
            if success:
                success_count += 1
            else:
                logger.warning(f"Failed to deliver notification {intent.intent_id} to {target.interface} ({target.target_type}).")
                
        # If at least one delivery succeeded, we consider it a success for the dispatcher
        if success_count == 0:
            logger.warning(f"Failed to deliver notification {intent.intent_id} to ANY target. Storing as pending.")
            self.store.add_pending(intent)
            self._record_signal(
                intent=intent,
                signal_type="behavioral",
                signal_name="delivery_failure",
                value=True,
                context={"target_count": len(targets)},
                source="system_observer",
            )
            return False
        self._record_signal(
            intent=intent,
            signal_type="behavioral",
            signal_name="delivery_success",
            value=True,
            context={"target_count": len(targets), "success_count": success_count},
            source="system_observer",
        )
        return True

    def record_feedback_signal(
        self,
        *,
        user_id: str,
        signal_name: str,
        value: Any,
        signal_type: str = "explicit",
        source: str = "user_feedback",
        context: Optional[Dict[str, Any]] = None,
        source_domain: str = "notifications",
        intent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        signal = self._build_signal(
            user_id=user_id,
            signal_name=signal_name,
            value=value,
            signal_type=signal_type,
            source=source,
            source_domain=source_domain,
            intent_id=intent_id,
            context=context,
        )
        history = self.store.get_signal_history(
            user_id=user_id,
            signal_name=signal_name,
            lookback_days=30,
        )
        self.store.add_learning_signal(signal)
        assessment = self.signal_confidence_engine.assess(signal=signal, history=history)
        self.store.add_signal_assessment(assessment)
        self._maybe_create_policy_suggestion(signal=signal, assessment=assessment)
        self._monitor_patch_health(signal=signal)
        return {"signal": signal, "assessment": assessment}

    def _record_signal(
        self,
        *,
        intent: NotificationIntent,
        signal_type: str,
        signal_name: str,
        value: Any,
        context: Optional[Dict[str, Any]] = None,
        source: str = "system_observer",
    ):
        try:
            signal = self._build_signal(
                user_id=intent.target_user_id,
                signal_name=signal_name,
                value=value,
                signal_type=signal_type,
                source=source,
                source_domain=intent.source_domain,
                intent_id=intent.intent_id,
                context={
                    **(context or {}),
                    "priority": intent.priority.value if hasattr(intent.priority, "value") else str(intent.priority),
                    "delivery_mode": intent.delivery_mode.value if hasattr(intent.delivery_mode, "value") else str(intent.delivery_mode),
                    "preferred_channel": intent.preferred_channel,
                    "event_type": str((intent.metadata or {}).get("event_type") or ""),
                },
            )
            history = self.store.get_signal_history(
                user_id=intent.target_user_id,
                signal_name=signal_name,
                lookback_days=30,
            )
            self.store.add_learning_signal(signal)
            assessment = self.signal_confidence_engine.assess(signal=signal, history=history)
            self.store.add_signal_assessment(assessment)
            self._maybe_create_policy_suggestion(signal=signal, assessment=assessment)
            self._monitor_patch_health(signal=signal)
        except Exception as e:
            logger.debug("Failed to record learning signal %s: %s", signal_name, e)

    @staticmethod
    def _build_signal(
        *,
        user_id: str,
        signal_name: str,
        value: Any,
        signal_type: str,
        source: str,
        source_domain: str,
        intent_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "signal_id": f"sig_{uuid.uuid4().hex[:10]}",
            "created_at": float(time.time()),
            "user_id": str(user_id or "default"),
            "signal_name": str(signal_name or "").strip().lower(),
            "signal_type": str(signal_type or "implicit").strip().lower(),
            "value": value,
            "source": str(source or "system_observer").strip().lower(),
            "source_domain": str(source_domain or "notifications").strip().lower(),
            "intent_id": str(intent_id or "").strip(),
            "context": context if isinstance(context, dict) else {},
        }

    def _maybe_create_policy_suggestion(self, *, signal: Dict[str, Any], assessment: Dict[str, Any]):
        if not isinstance(signal, dict) or not isinstance(assessment, dict):
            return
        if not bool(assessment.get("eligible_patch_recommendation")):
            return
        recommendation = assessment.get("patch_recommendation")
        if not isinstance(recommendation, dict):
            return

        signal_name = str(signal.get("signal_name") or "").strip().lower()
        target = str(recommendation.get("target") or "").strip().lower()
        user_id = str(signal.get("user_id") or "").strip()
        proposal = recommendation.get("proposal") if isinstance(recommendation.get("proposal"), dict) else {}
        fp = f"{user_id}|{target}|{signal_name}|{proposal}"
        suggestion = {
            "suggestion_id": f"psg_{uuid.uuid4().hex[:10]}",
            "created_at": float(time.time()),
            "status": "pending",
            "requires_user_approval": True,
            "mode": "observe_only_no_auto_patch",
            "user_id": user_id,
            "signal_id": str(signal.get("signal_id") or ""),
            "assessment_id": str(assessment.get("assessment_id") or ""),
            "signal_name": signal_name,
            "target": target,
            "reason": str(recommendation.get("reason") or ""),
            "proposal": proposal,
            "confidence_score": float(assessment.get("confidence_score") or 0.0),
            "policy_version": str((signal.get("context") or {}).get("policy_version") or ""),
            "preference_version": (signal.get("context") or {}).get("preference_version"),
            "fingerprint": fp,
        }
        stored = self.store.add_policy_suggestion(suggestion)
        if stored:
            logger.info(
                "Policy suggestion registered | id=%s user=%s target=%s confidence=%.3f",
                stored.get("suggestion_id"),
                stored.get("user_id"),
                stored.get("target"),
                float(stored.get("confidence_score") or 0.0),
            )

    def _monitor_patch_health(self, *, signal: Dict[str, Any]):
        if not isinstance(signal, dict):
            return
        user_id = str(signal.get("user_id") or "").strip()
        signal_name = str(signal.get("signal_name") or "").strip().lower()
        if not user_id or signal_name not in {"delivery_success", "delivery_failure"}:
            return
        result = self.store.record_patch_delivery_outcome(user_id=user_id, signal_name=signal_name)
        if isinstance(result, dict) and bool(result.get("ok")):
            applied = result.get("applied_patch") if isinstance(result.get("applied_patch"), dict) else {}
            if str(applied.get("status") or "").strip().lower() == "rolled_back":
                logger.warning(
                    "Automatic rollback triggered for applied patch | applied_id=%s user=%s",
                    applied.get("applied_id"),
                    user_id,
                )

    def _fingerprint(self, intent: NotificationIntent) -> str:
        md = intent.metadata if isinstance(intent.metadata, dict) else {}
        dedupe_key = str(md.get("dedupe_key") or "").strip()
        if dedupe_key:
            return f"dk:{dedupe_key}"
        event_id = str(md.get("event_id") or "").strip()
        event_type = str(md.get("event_type") or "").strip()
        if event_id:
            return f"event:{event_type}:{event_id}:{intent.target_user_id}"
        return f"msg:{intent.source_domain}:{intent.target_user_id}:{intent.title or ''}:{intent.message}"

    def _prune_fingerprints(self, now: float):
        stale = [k for k, ts in self._recent_fingerprints.items() if (now - ts) > self._dedupe_ttl_sec]
        for k in stale:
            self._recent_fingerprints.pop(k, None)

    def _send_to_session(self, session_id: str, intent: NotificationIntent):
        """
        Delivers to a specific session via the kernel.
        """
        # We use a special formatted message or a direct driver call if possible.
        # For this phase, we'll use kernel.orchestrator._send_to_session which is already robust.
        # However, we want to distinguish this as a notification.
        
        md = intent.metadata if isinstance(intent.metadata, dict) else {}
        if bool(md.get("route_via_session_llm")):
            return self._inject_notification_event(session_id, intent)

        notification_text = self._build_delivery_text(intent, channel="session")
        
        # Access kernel for delivery. Kernel MUST have _send_to_session.
        # CapabilityLoader ensures the correct kernel is propagated.
        if self.kernel and hasattr(self.kernel, "_send_to_session"):
            logger.info(f"Delivering notification to session {session_id} via kernel.")
            return self.kernel._send_to_session(session_id, notification_text, phase="notification")
        
        # Log critical failure if delivery mechanism is missing
        logger.error(f"Failed to deliver notification to session {session_id}: Kernel missing _send_to_session method or not initialized.")
        if not self.kernel:
            logger.error("NotificationDispatcher.kernel is None.")
        else:
            logger.error(f"NotificationDispatcher.kernel type: {type(self.kernel)}")
            
        return False

    def _inject_notification_event(self, session_id: str, intent: NotificationIntent) -> bool:
        """
        Injects a structured internal event into the target user session.
        The target session LLM is responsible for producing the final user-facing message.
        """
        if not self.kernel:
            logger.error("Cannot inject notification event: kernel is None.")
            return False

        internal_driver = getattr(self.kernel, "internal_driver", None)
        if not internal_driver or not hasattr(internal_driver, "inject_event"):
            logger.error("Cannot inject notification event: InternalDriver unavailable.")
            return False

        md = intent.metadata if isinstance(intent.metadata, dict) else {}
        payload = {
            "title": intent.title,
            "message": intent.message,
            "priority": intent.priority.value if hasattr(intent.priority, "value") else str(intent.priority),
            "source_domain": intent.source_domain,
            "target_user_id": intent.target_user_id,
            "delivery_mode": intent.delivery_mode.value if hasattr(intent.delivery_mode, "value") else str(intent.delivery_mode),
            "message_context": md,
            "handling_envelope": {
                "goal": str(md.get("notification_goal") or "notify_user"),
                "kind": "system_notification_event",
                "treat_as": "internal_notification",
                "finalize_with_persona": True,
                "do_not_treat_as_user_message": True,
            },
        }

        priority_value = intent.priority.value if hasattr(intent.priority, "value") else str(intent.priority or "medium")
        event = AgentEvent(
            event_type="notification.user_alert",
            source=f"notification_dispatcher.{intent.source_domain}",
            priority=priority_value,
            target_user_id=intent.target_user_id,
            target_session_id=session_id,
            payload=payload,
            metadata={
                **md,
                "notification_intent_id": intent.intent_id,
                "event_type": "notification.user_alert",
            },
        )

        try:
            internal_driver.inject_event(
                event,
                session_id=session_id,
                metadata={"__notification_dispatch": True},
            )
            logger.info(
                "Injected notification event into target session | session=%s intent=%s",
                session_id,
                intent.intent_id,
            )
            return True
        except Exception as e:
            logger.error("Failed injecting notification event into session %s: %s", session_id, e)
            return False

    def _send_to_push(self, interface: str, intent: NotificationIntent):
        """
        Delivers to a push-capable driver (e.g., Telegram).
        """
        # Find the driver in the kernel
        driver = getattr(self.kernel, f"{interface}_driver", None)
        if not driver:
            logger.error(f"Push driver for {interface} not found.")
            return False
            
        try:
            # Most drivers have a send_response or similar. 
            # We need to resolve the user's chat_id/target for push.
            # In Phase 5, we assume the user_id maps to the push target.
            
            push_text = self._build_delivery_text(intent, channel="push")
            
            # Simple heuristic: for Telegram, target is often the user_id (if it starts with telegram_)
            target = intent.target_user_id
            
            if hasattr(driver, "send_response"):
                driver.send_response(push_text, target=target)
                return True
        except Exception as e:
            logger.error(f"Error sending push notification via {interface}: {e}")
            
        return False

    def _build_delivery_text(self, intent: NotificationIntent, channel: str) -> str:
        md = intent.metadata if isinstance(intent.metadata, dict) else {}
        message = str(intent.message or "").strip()
        title = str(intent.title or "").strip()
        rendered_by_agent = bool(md.get("rendered_by_agent") or md.get("raw_user_facing"))
        suppress_legacy = bool(md.get("suppress_legacy_prefix"))

        if rendered_by_agent or suppress_legacy:
            return message

        if channel == "session":
            prefix = f"[{intent.priority.upper()}] " if intent.priority in [NotificationPriority.HIGH, NotificationPriority.CRITICAL] else ""
            return f"{prefix}{title + ': ' if title else ''}{message}"

        if channel == "push":
            if title:
                return f"🔔 *{title}*\n{message}"
            return f"🔔 {message}"

        return message
