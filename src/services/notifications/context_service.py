import logging
from typing import List, Dict, Optional

logger = logging.getLogger("CommunicationContextService")

class CommunicationContextService:
    def __init__(self, orchestrator: object):
        self.orchestrator = orchestrator

    def list_active_sessions(self, user_id: str) -> List[Dict]:
        """
        Returns a list of active sessions for the user.
        Prioritizes sessions with active real-time connections (WebSockets).
        """
        all_sessions = self.orchestrator.get_sessions_list(interface="all")
        # In this phase, user_id is often the same as session_id or mapped to it.
        # We look for sessions where the user is the principal.
        
        user_sessions = [
            s for s in all_sessions 
            if s.get("session_id") == user_id or s.get("user_id") == user_id
        ]
        
        # Check for real-time presence via ServerDriver (if available)
        active_ws_sessions = []
        if hasattr(self.orchestrator, "server_driver") and self.orchestrator.server_driver:
            manager = getattr(self.orchestrator.server_driver, "connection_manager", None)
            if manager:
                active_ws_sessions = list(manager.active_connections.keys())
        
        for s in user_sessions:
            s["has_active_connection"] = s["session_id"] in active_ws_sessions
            
        # Sort so sessions with active connections come first
        user_sessions.sort(key=lambda x: x.get("has_active_connection", False), reverse=True)
        return user_sessions

    def list_push_channels(self, user_id: str) -> List[Dict]:
        """
        Returns a list of channels capable of push notifications (e.g., Telegram).
        """
        channels = []
        kernel = getattr(self.orchestrator, "kernel", None)
        if not kernel:
            return []
            
        # Check if Telegram is enabled and configured
        if hasattr(kernel, "telegram_driver") and kernel.telegram_driver:
            # We assume Telegram is always 'available' as a push channel if enabled
            channels.append({
                "interface": "telegram",
                "push_capable": True
            })
            
        # Add other drivers here as they become push-capable
        return channels

    def get_best_target(self, user_id: str, preferred_mode: str = "active_session_preferred") -> Optional[Dict]:
        """
        Implements the resolution hierarchy:
        1. Active Web Session (with WebSocket)
        2. Push Channel (Telegram)
        3. Fallback to Pending
        """
        active_sessions = self.list_active_sessions(user_id)
        
        # 1. Prefer active web session with live connection
        for session in active_sessions:
            if session.get("has_active_connection") and session.get("interface") == "web":
                return {
                    "type": "session",
                    "target_id": session["session_id"],
                    "interface": "web"
                }
                
        # 2. Try push channels if allowed
        if preferred_mode in ["active_session_preferred", "push_allowed"]:
            push_channels = self.list_push_channels(user_id)
            if push_channels:
                # For now, just pick the first available push channel
                return {
                    "type": "push",
                    "interface": push_channels[0]["interface"]
                }
                
        # 3. Last resort: most recent session (even if not connected)
        if active_sessions:
            return {
                "type": "session",
                "target_id": active_sessions[0]["session_id"],
                "interface": active_sessions[0].get("interface", "web")
            }
            
        return None
