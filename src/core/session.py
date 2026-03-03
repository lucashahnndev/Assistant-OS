
from typing import List, Dict, Optional
import datetime
import time
import uuid
from typing import List, Dict, Optional, Any
from utils.event_bus import global_event_bus

class Session:
    def __init__(self, session_id: str, source: str = "web"):
        self.session_id = session_id
        self.source = source
        self.name = "" # Display name for the session
        self.name_generated = False # Flag for whether the LLM auto-generated the name
        self.profile_picture = "" # Path or URL to the session's avatar
        self.created_at = time.time()
        self.last_interaction = time.time()
        self.last_opened_at = time.time()
        self.history: List[Dict[str, str]] = []
        self.context: Dict[str, any] = {}
        self.summary: str = ""
        self.scratchpad: str = ""
        self.plan: List[str] = []
        self.state_summary: Dict[str, any] = {
            "goal": "Standby",
            "cursor": "0/0 (step: init)",
            "done_steps": [],
            "last_outcome": "None",
            "last_error": "None",
            "retry_count": 0,
            "backoff_strategy": "None",
            "memory_notes": "None"
        }
        self.pending_action: Optional[Dict] = None # Stores {action, params} for HITL
        self.drivers_state: Dict[str, Any] = {} # Persistent state for specific drivers (e.g. browser tabs)

    def add_message(self, role: str, content: str, file: Optional[Dict] = None, attachments: Optional[List[Dict]] = None, msg_type: str = "default", summary: str = None, work_id: str = None):
        # Rough token estimation (chars / 4)
        tokens = len(content) // 4
        timestamp = datetime.datetime.now().isoformat()
        msg = {
            "id": str(uuid.uuid4()),
            "role": role, 
            "content": content, 
            "tokens": tokens, 
            "type": msg_type,
            "timestamp": timestamp,
            "is_read": role == "user" # Agent "reads" user messages immediately
        }
        if work_id:
            msg["work_id"] = work_id
            
        if summary:
            msg["summary"] = summary
            # When summary is present, LLM context should focus on summary
            msg["tokens"] = len(summary) // 4
            
        if file:
            msg["file"] = file
        if attachments:
            msg["attachments"] = attachments
        self.history.append(msg)
        self.last_interaction = time.time()
        
        # Emit event for real-time synchronization
        global_event_bus.emit_threadsafe({
            "type": "message_added",
            "session_id": self.session_id,
            "role": role,
            "message": msg,
            "msg_type": msg_type,
            "work_id": work_id,
            "unread_count": self.get_unread_count("assistant")
        })

    def get_history(self) -> List[Dict[str, str]]:
        return self.history

    def mark_as_read(self, role: str = "assistant"):
        """Marks all messages from a specific role as read."""
        changed = False
        for msg in self.history:
            if msg.get("role") == role and not msg.get("is_read", False):
                msg["is_read"] = True
                changed = True
        return changed

    def get_unread_count(self, role: str = "assistant") -> int:
        """Returns the number of unread messages from a specific role."""
        return sum(1 for msg in self.history if msg.get("role") == role and not msg.get("is_read", False))

    def clear_history(self):
        self.history = []

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "source": self.source,
            "name": self.name,
            "name_generated": self.name_generated,
            "profile_picture": self.profile_picture,
            "created_at": self.created_at,
            "last_interaction": self.last_interaction,
            "last_opened_at": getattr(self, 'last_opened_at', self.last_interaction),
            "history": self.history,
            "context": self.context,
            "summary": self.summary,
            "scratchpad": self.scratchpad,
            "plan": self.plan,
            "state_summary": self.state_summary,
            "pending_action": self.pending_action,
            "drivers_state": self.drivers_state
        }

    @classmethod
    def from_dict(cls, data: Dict):
        session = cls(data["session_id"], data.get("source", "web"))
        session.name = data.get("name", "")
        session.name_generated = data.get("name_generated", False)
        session.profile_picture = data.get("profile_picture", "")
        session.created_at = data.get("created_at", time.time())
        session.last_interaction = data.get("last_interaction", time.time())
        session.last_opened_at = data.get("last_opened_at", session.last_interaction)
        session.history = data.get("history", [])
        
        # Ensure all history items have an ID (for legacy data)
        for msg in session.history:
            if "id" not in msg:
                msg["id"] = str(uuid.uuid4())
            if "timestamp" not in msg:
                msg["timestamp"] = datetime.datetime.now().isoformat()
            if "is_read" not in msg:
                # Default: assistant messages old history as read, unless we want to flag them
                msg["is_read"] = True
                
        session.context = data.get("context", {})
        session.summary = data.get("summary", "")
        session.scratchpad = data.get("scratchpad", "")
        session.plan = data.get("plan", [])
        session.state_summary = data.get("state_summary", {
            "goal": "Standby",
            "cursor": "0/0 (step: init)",
            "done_steps": [],
            "last_outcome": "None",
            "last_error": "None",
            "retry_count": 0,
            "backoff_strategy": "None",
            "memory_notes": "None"
        })
        session.pending_action = data.get("pending_action")
        session.drivers_state = data.get("drivers_state", {})
        return session

    def get_context_for_llm(self, limit_tokens: int = 6000, limit_msgs: int = 30) -> List[Dict[str, str]]:
        """Returns the last N messages within the token limit."""
        context = []
        total_tokens = 0
        
        # Iterate backwards through history
        for msg in reversed(self.history):
            msg_tokens = msg.get("tokens", len(msg["content"]) // 4)
            if total_tokens + msg_tokens > limit_tokens or len(context) >= limit_msgs:
                break
            
            # Create a clean message for the LLM
            # Preference: summary > content
            llm_content = msg.get("summary", msg["content"])
            
            # Open-weight models often drop mid-conversation "system" messages.
            # Convert system observations to "user" role to guarantee processing.
            clean_role = msg["role"]
            if clean_role == "system":
                clean_role = "user"
                llm_content = f"[SYSTEM/OBSERVATION]:\n{llm_content}"
                
            clean_msg = {"role": clean_role, "content": llm_content}
            
            # Preserve attachments and file metadata for agent awareness
            if "attachments" in msg:
                clean_msg["attachments"] = msg["attachments"]
            if "file" in msg:
                clean_msg["file"] = msg["file"]
                
            context.insert(0, clean_msg)
            total_tokens += msg_tokens
            
        return context
