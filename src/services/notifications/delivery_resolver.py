from typing import Optional, Dict, List
from .models import NotificationIntent, DeliveryMode

class DeliveryTarget:
    def __init__(self, target_type: str, target_id: Optional[str], interface: str):
        self.target_type = target_type  # "session" or "push"
        self.target_id = target_id      # session_id or None for push
        self.interface = interface      # "web", "telegram", etc.

class DeliveryResolver:
    def __init__(self, context_service):
        self.context_service = context_service

    def resolve(self, intent: NotificationIntent) -> List[DeliveryTarget]:
        """Determines where the notification should be delivered."""
        user_id = intent.target_user_id or "default"
        targets: List[DeliveryTarget] = []
        seen = set()
        md = intent.metadata if isinstance(intent.metadata, dict) else {}
        disallow_push = bool(md.get("disallow_push"))
        queue_if_active_conversation = bool(md.get("queue_if_active_conversation"))
        preferred_channel = str(
            intent.preferred_channel or md.get("preferred_channel_from_preference") or ""
        ).strip().lower()
        active_sessions = self.context_service.list_active_sessions(user_id)

        if queue_if_active_conversation and any(bool(s.get("has_active_connection")) for s in active_sessions):
            # Hard user preference: do not interrupt while in active conversation.
            return []

        def add_target(target_type: str, target_id: Optional[str], interface: str):
            key = (str(target_type or ""), str(target_id or ""), str(interface or ""))
            if key in seen:
                return
            seen.add(key)
            targets.append(DeliveryTarget(target_type=target_type, target_id=target_id, interface=interface))
        
        # 0. Session-LLM routing: keep notification structured and inject only into sessions.
        if bool(md.get("route_via_session_llm")):
            if intent.target_session_id:
                add_target(
                    target_type="session",
                    target_id=intent.target_session_id,
                    interface="web",
                )
                return targets

            if active_sessions:
                add_target(
                    target_type="session",
                    target_id=active_sessions[0]["session_id"],
                    interface=active_sessions[0].get("interface", "web"),
                )
                return targets

        # 0.5 Preferred channel routing when available.
        if preferred_channel == "telegram" and not disallow_push and intent.delivery_mode != DeliveryMode.SESSION_ONLY:
            push_channels = self.context_service.list_push_channels(user_id)
            telegram_available = next((c for c in push_channels if c.get("interface") == "telegram"), None)
            if telegram_available:
                add_target(target_type="push", target_id=None, interface="telegram")
                return targets

        if preferred_channel in {"web", "session"} and active_sessions:
            add_target(
                target_type="session",
                target_id=active_sessions[0]["session_id"],
                interface=active_sessions[0].get("interface", "web"),
            )
            return targets

        # 1. Broad Broadcast for system-wide/admin notifications
        # If the source is 'system' or 'admin', we want to reach all active human sessions
        if intent.source_domain in ["system", "admin", "calendar"]:
            # Find ALL active sessions for the user
            for session in active_sessions:
                add_target(
                    target_type="session",
                    target_id=session["session_id"],
                    interface=session.get("interface", "web")
                )
            
            # Also add ALL push channels
            if intent.delivery_mode != DeliveryMode.SESSION_ONLY and not disallow_push:
                push_channels = self.context_service.list_push_channels(user_id)
                for channel in push_channels:
                    # Avoid duplicate push when same interface already has a concrete active session.
                    has_session_same_interface = any(
                        t.target_type == "session" and t.interface == channel["interface"] for t in targets
                    )
                    if has_session_same_interface:
                        continue
                    add_target(
                        target_type="push",
                        target_id=None,
                        interface=channel["interface"]
                    )
            
            if targets:
                return targets

        # 2. Targeted logic for specific requests
        if intent.target_session_id and intent.delivery_mode == DeliveryMode.SESSION_ONLY:
            add_target(
                target_type="session",
                target_id=intent.target_session_id,
                interface="web" # Assume web
            )
            return targets
            
        # 3. Fallback to 'best' target logic
        preferred_mode = intent.delivery_mode
        if disallow_push and preferred_mode != DeliveryMode.SESSION_ONLY:
            preferred_mode = DeliveryMode.SESSION_ONLY
        best = self.context_service.get_best_target(user_id, preferred_mode=preferred_mode)
        if best:
            add_target(
                target_type=best["type"],
                target_id=best.get("target_id"),
                interface=best["interface"]
            )
            return targets
            
        return []
