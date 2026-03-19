import uuid
import datetime
from enum import Enum
from typing import Dict, Any, Optional

class AgentEventPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class AgentEvent:
    """
    Canonical envelope for internal events meant to wake up a system session.
    """
    def __init__(
        self,
        event_type: str,
        source: str,
        event_id: Optional[str] = None,
        priority: AgentEventPriority = AgentEventPriority.MEDIUM,
        target_user_id: str = "system",
        target_session_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[str] = None,
        requires_attention: bool = True,
        trace_id: Optional[str] = None
    ):
        self.event_id = event_id or str(uuid.uuid4())
        self.event_type = event_type
        self.source = source
        self.priority = AgentEventPriority(priority) if isinstance(priority, str) else priority
        self.target_user_id = target_user_id
        self.target_session_id = target_session_id
        self.payload = payload or {}
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.requires_attention = requires_attention
        self.trace_id = trace_id

    @staticmethod
    def validate_iso8601(v: str) -> str:
        try:
            datetime.datetime.fromisoformat(v.replace('Z', '+00:00'))
            return v
        except ValueError:
            raise ValueError("created_at must be in ISO8601 format")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "priority": self.priority.value if isinstance(self.priority, AgentEventPriority) else self.priority,
            "target_user_id": self.target_user_id,
            "target_session_id": self.target_session_id,
            "payload": self.payload,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "requires_attention": self.requires_attention,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(**data)

    def as_text(self) -> str:
        """
        Returns a textual representation of the event for agent reasoning.
        """
        priority_label = f"[{self.priority.upper()} PRIORITY]" if self.priority != AgentEventPriority.MEDIUM else ""
        text = f"[INTERNAL_EVENT] {priority_label}\n"
        text += f"Type: {self.event_type}\n"
        text += f"Source: {self.source}\n"
        # Notification events should be verbalized as a user-facing reminder,
        # not as a meta acknowledgement of internal system receipt.
        if str(self.event_type).startswith("notification."):
            text += (
                "Handling: Notify the user directly as a reminder/alert. "
                "Do NOT say you received this event. "
                "Do NOT mention internal loops/events.\n"
            )
        if self.payload:
            text += f"Payload: {self.payload}\n"
        return text.strip()
