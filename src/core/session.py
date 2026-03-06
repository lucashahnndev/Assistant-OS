import json
import logging
import uuid
import datetime
import time
from typing import Optional, List, Dict, Callable, Any
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
        self.task_registry: Dict[str, Dict[str, Any]] = {} # task_id -> task_metadata_dict
        self.event_history: List[Dict[str, Any]] = [] # Ring buffer of Worker events
        self._max_event_history = 100
        self.turn_id: int = 0 # Monotonic turn counter
        self.active_focus_task_id: Optional[str] = None
        self.active_focus_group: Optional[str] = None
        self.memory: List[Dict[str, Any]] = [] # Session-scope memory (accepted)
        self.candidate_store: List[Dict[str, Any]] = [] # Worker-proposed candidates

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
        self.turn_id += 1 # Advance turn counter
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
            "drivers_state": self.drivers_state,
            "task_registry": self.task_registry,
            "event_history": self.event_history,
            "turn_id": self.turn_id,
            "active_focus_task_id": self.active_focus_task_id,
            "active_focus_group": self.active_focus_group,
            "memory": self.memory,
            "candidate_store": self.candidate_store
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
        session.task_registry = data.get("task_registry", {})
        session.event_history = data.get("event_history", [])
        session.turn_id = data.get("turn_id", 0)
        session.active_focus_task_id = data.get("active_focus_task_id")
        session.active_focus_group = data.get("active_focus_group")
        session.memory = data.get("memory", [])
        session.candidate_store = data.get("candidate_store", [])
        return session

    def publish_event(self, event: Dict[str, Any]):
        """Publishes a Worker event to the session inbox with deduplication and ring buffer."""
        # Ensure mandatory metadata
        if "event_id" not in event:
            event["event_id"] = str(uuid.uuid4())
        if "timestamp" not in event:
            event["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        event_id = event.get("event_id")

        # Deduplicate
        if any(e.get("event_id") == event_id for e in self.event_history) or \
           any(e.get("memory_id") == event.get("memory_id") for e in self.candidate_store):
            return

        # Divert MEMORY_CANDIDATE to candidate_store
        e_type = str(event.get("event_type") or "").upper()
        if e_type == "MEMORY_CANDIDATE":
            self.candidate_store.append(event)
            return

        # Add to standard history
        self.event_history.append(event)

        # Maintain ring buffer
        if len(self.event_history) > self._max_event_history:
            self.event_history.pop(0)

        # Update task registry with metadata
        task_id = event.get("task_id")
        if task_id:
            e_type = str(event.get("event_type") or "").upper()
            if task_id not in self.task_registry:
                # Initialization
                self.task_registry[task_id] = {
                    "task_id": task_id,
                    "task_role": event.get("task_role", "unknown task"),
                    "status": e_type,
                    "base_turn_id": event.get("base_turn_id", self.turn_id),
                    "created_at": time.time(),
                    "last_event_at": time.time(),
                    "attention_level": event.get("attention_level", "LOW"),
                    "intent_group_id": event.get("intent_group_id"),
                    "is_stale": False,
                    "is_relevant_to_current_focus": False,
                    "is_superseded": False,
                    "user_visible": False,
                    "mentioned_to_user": False,
                    "waiting_user_response": False,
                    "announced_completion": False,
                    "last_summary": event.get("summary", ""),
                    "last_failure_summary": event.get("failure_summary", ""),
                    "last_outcome": event.get("outcome", "")
                }
            else:
                # Update
                task = self.task_registry[task_id]
                task["status"] = e_type
                task["last_event_at"] = time.time()
                task["attention_level"] = event.get("attention_level", task["attention_level"])
                # Merge summaries if present
                if event.get("summary"): 
                    task["last_summary"] = event["summary"]
                if event.get("failure_summary"):
                    task["last_failure_summary"] = event["failure_summary"]
                if event.get("outcome"):
                    task["last_outcome"] = event["outcome"]
                if event.get("intent_group_id"):
                    task["intent_group_id"] = event["intent_group_id"]

    def drain_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Drains the earliest N events from the history (FIFO)."""
        drained = self.event_history[:limit]
        self.event_history = self.event_history[limit:]
        return drained

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
