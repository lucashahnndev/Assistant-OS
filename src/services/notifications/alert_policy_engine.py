import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .models import DeliveryMode, NotificationIntent
from .user_preferences import UserPreferenceStore

logger = logging.getLogger("AlertPolicyEngine")


class AlertPolicyEngine:
    """
    Phase-0 policy engine:
    - deterministic execution path
    - applies explicit user preferences as hard constraints
    - no adaptive policy patches yet
    """

    POLICY_VERSION = "calendar_adaptive_alerts_v3.phase0"

    def __init__(self, preference_store: UserPreferenceStore, notification_store=None):
        self.preference_store = preference_store
        self.notification_store = notification_store

    def apply(
        self,
        intent: NotificationIntent,
        *,
        resolver_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[NotificationIntent, Dict[str, Any]]:
        md = intent.metadata if isinstance(intent.metadata, dict) else {}
        md = dict(md)
        domain = str(intent.source_domain or "").strip().lower()
        event_type = str(md.get("event_type") or "").strip().lower()
        user_id = str(intent.target_user_id or "default")

        effective_preferences = self.preference_store.get_effective_preferences(
            user_id=user_id,
            domain=domain or None,
            event_type=event_type or None,
            context_tags=[],
        )
        explicit_dimensions = {str(p.get("dimension") or "").strip().lower() for p in effective_preferences}
        pref_version = self.preference_store.get_user_preference_version(user_id)

        decision_trace: Dict[str, Any] = {
            "decision_id": f"ntf_dec_{uuid.uuid4().hex[:10]}",
            "created_at": float(time.time()),
            "source_domain": domain,
            "target_user_id": user_id,
            "policy_version": self.POLICY_VERSION,
            "preference_version": pref_version,
            "matched_preferences": [
                {
                    "preference_id": p.get("preference_id"),
                    "dimension": p.get("dimension"),
                    "key": p.get("key"),
                    "priority": p.get("priority"),
                    "version": p.get("version"),
                }
                for p in effective_preferences
            ],
            "applied_rules": [],
            "notes": [],
        }

        style_hints: List[str] = []
        preferred_channel = intent.preferred_channel
        disallow_push = False
        queue_if_active_conversation = False

        for pref in effective_preferences:
            dim = str(pref.get("dimension") or "").strip().lower()
            key = str(pref.get("key") or "").strip().lower()
            value = pref.get("value")
            pref_id = str(pref.get("preference_id") or "")

            if dim == "channel":
                if key == "allow_push" and value is False:
                    disallow_push = True
                    intent.delivery_mode = DeliveryMode.SESSION_ONLY
                    decision_trace["applied_rules"].append(f"{pref_id}:channel.allow_push=false")
                elif key == "preferred_channel" and value:
                    preferred_channel = str(value).strip().lower()
                    decision_trace["applied_rules"].append(f"{pref_id}:channel.preferred_channel={preferred_channel}")

            elif dim == "style":
                if key == "style_mode" and value:
                    style_hints.append(str(value).strip().lower())
                    decision_trace["applied_rules"].append(f"{pref_id}:style.style_mode={value}")

            elif dim == "interruptibility":
                if key == "allow_interrupt_active_conversation" and value is False:
                    queue_if_active_conversation = True
                    md["interruptibility"] = "low"
                    decision_trace["applied_rules"].append(
                        f"{pref_id}:interruptibility.allow_interrupt_active_conversation=false"
                    )

            elif dim == "timing":
                if key == "default_reminder_offset_minutes":
                    md["timing_preference_minutes"] = value
                    decision_trace["applied_rules"].append(f"{pref_id}:timing.default_reminder_offset_minutes={value}")
                    decision_trace["notes"].append(
                        "Timing preference recorded; scheduler/observer integration is outside dispatcher phase-0 scope."
                    )

        if disallow_push:
            md["disallow_push"] = True
        if preferred_channel:
            intent.preferred_channel = preferred_channel
            md["preferred_channel_from_preference"] = preferred_channel
        if queue_if_active_conversation:
            md["queue_if_active_conversation"] = True

        if style_hints:
            style_instruction = self._style_instruction(style_hints)
            if style_instruction:
                existing_instruction = str(md.get("instruction") or "").strip()
                if existing_instruction:
                    md["instruction"] = f"{existing_instruction} {style_instruction}".strip()
                else:
                    md["instruction"] = style_instruction

        # Adaptive/manual patch overrides (lower precedence than explicit user preferences).
        if self.notification_store is not None:
            overrides = self.notification_store.get_runtime_overrides_for_user(user_id)
            if isinstance(overrides, dict):
                self._apply_runtime_overrides(
                    intent=intent,
                    metadata=md,
                    overrides=overrides,
                    explicit_dimensions=explicit_dimensions,
                    decision_trace=decision_trace,
                )

        md["policy_version"] = self.POLICY_VERSION
        md["preference_version"] = pref_version
        md["decision_trace"] = decision_trace
        intent.metadata = md

        decision_trace["final_delivery_mode"] = (
            intent.delivery_mode.value if hasattr(intent.delivery_mode, "value") else str(intent.delivery_mode)
        )
        decision_trace["final_preferred_channel"] = intent.preferred_channel
        decision_trace["final_interruptibility"] = str(md.get("interruptibility") or "medium")
        decision_trace["used_explicit_preferences"] = bool(effective_preferences)
        decision_trace["enforcement_mode"] = "explicit_preferences_only"
        return intent, decision_trace

    @staticmethod
    def _apply_runtime_overrides(
        *,
        intent: NotificationIntent,
        metadata: Dict[str, Any],
        overrides: Dict[str, Dict],
        explicit_dimensions: set,
        decision_trace: Dict[str, Any],
    ):
        # channel_policy overrides
        channel = overrides.get("channel_policy") if isinstance(overrides.get("channel_policy"), dict) else {}
        channel_proposal = channel.get("proposal") if isinstance(channel.get("proposal"), dict) else {}
        if channel_proposal and "channel" not in explicit_dimensions:
            if "disallow_push" in channel_proposal and bool(channel_proposal.get("disallow_push")):
                metadata["disallow_push"] = True
                intent.delivery_mode = DeliveryMode.SESSION_ONLY
                decision_trace["applied_rules"].append("runtime_override:channel_policy.disallow_push=true")
            if "preferred_channel" in channel_proposal and channel_proposal.get("preferred_channel"):
                if not metadata.get("preferred_channel_from_preference"):
                    intent.preferred_channel = str(channel_proposal.get("preferred_channel")).strip().lower()
                    decision_trace["applied_rules"].append(
                        f"runtime_override:channel_policy.preferred_channel={intent.preferred_channel}"
                    )

        # timing_policy overrides
        timing = overrides.get("timing_policy") if isinstance(overrides.get("timing_policy"), dict) else {}
        timing_proposal = timing.get("proposal") if isinstance(timing.get("proposal"), dict) else {}
        if timing_proposal and "timing" not in explicit_dimensions:
            if "default_reminder_offset_minutes" in timing_proposal:
                metadata["timing_preference_minutes"] = timing_proposal.get("default_reminder_offset_minutes")
                decision_trace["applied_rules"].append("runtime_override:timing_policy.default_reminder_offset_minutes")

        # style_policy overrides
        style = overrides.get("style_policy") if isinstance(overrides.get("style_policy"), dict) else {}
        style_proposal = style.get("proposal") if isinstance(style.get("proposal"), dict) else {}
        if style_proposal and "style" not in explicit_dimensions:
            mode = str(style_proposal.get("style_mode") or "").strip().lower()
            if mode:
                style_instruction = AlertPolicyEngine._style_instruction([mode])
                if style_instruction:
                    existing_instruction = str(metadata.get("instruction") or "").strip()
                    metadata["instruction"] = (
                        f"{existing_instruction} {style_instruction}".strip()
                        if existing_instruction else style_instruction
                    )
                    decision_trace["applied_rules"].append(f"runtime_override:style_policy.style_mode={mode}")

    @staticmethod
    def _style_instruction(style_hints: List[str]) -> str:
        hints = set(style_hints or [])
        if "direct_concise" in hints:
            return "Use tom direto e breve, com frases curtas."
        if "direct" in hints:
            return "Use tom direto."
        if "concise" in hints:
            return "Seja conciso."
        return ""
