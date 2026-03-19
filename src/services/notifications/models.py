from enum import Enum
from typing import Optional, Dict, Any
import datetime
import datetime
import uuid

class NotificationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class DeliveryMode(str, Enum):
    ACTIVE_SESSION_PREFERRED = "active_session_preferred"
    PUSH_ALLOWED = "push_allowed"
    SESSION_ONLY = "session_only"

class NotificationIntent:
    def __init__(
        self,
        source_domain: str,
        target_user_id: str,
        message: str,
        intent_id: Optional[str] = None,
        target_session_id: Optional[str] = None,
        title: Optional[str] = None,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        delivery_mode: DeliveryMode = DeliveryMode.ACTIVE_SESSION_PREFERRED,
        created_at: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        preferred_channel: Optional[str] = None,
        fallback_allowed: bool = True,
        thread_mode: Optional[str] = None,
        visibility: str = "public"
    ):
        self.intent_id = intent_id or f"nit_{uuid.uuid4().hex[:8]}"
        self.source_domain = source_domain
        self.target_user_id = target_user_id
        self.target_session_id = target_session_id
        self.title = title
        self.message = message
        self.priority = priority
        self.delivery_mode = delivery_mode
        self.created_at = created_at or datetime.datetime.now(datetime.timezone.utc).timestamp()
        self.metadata = metadata or {}
        self.preferred_channel = preferred_channel
        self.fallback_allowed = fallback_allowed
        self.thread_mode = thread_mode
        self.visibility = visibility

    def to_dict(self):
        return {
            "intent_id": self.intent_id,
            "source_domain": self.source_domain,
            "target_user_id": self.target_user_id,
            "target_session_id": self.target_session_id,
            "title": self.title,
            "message": self.message,
            "priority": self.priority,
            "delivery_mode": self.delivery_mode,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "preferred_channel": self.preferred_channel,
            "fallback_allowed": self.fallback_allowed,
            "thread_mode": self.thread_mode,
            "visibility": self.visibility
        }
