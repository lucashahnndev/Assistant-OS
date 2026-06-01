import json
import logging
import uuid
import datetime
import time
from typing import Optional, List, Dict, Callable, Any
from utils.event_bus import global_event_bus
from core.cognition import build_cognitive_frame, CognitiveFrame
from core.intents import IntentAgenda
from services.cognition import default_cognitive_state_dict
from config.manager import ConfigManager

SESSION_TYPE_USER = "user"
SESSION_TYPE_SYSTEM = "system"

class Session:
    def __init__(self, session_id: str, source: str = "web", session_type: str = SESSION_TYPE_USER, domain: Optional[str] = None):
        self.session_id = session_id
        self.source = source
        self.session_type = session_type
        self.domain = domain
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
            "last_observation": "None",
            "last_observation_evidence": "None",
            "last_observation_evidence_count": 0,
            "last_observation_evidence_shown": 0,
            "last_observation_evidence_truncated": False,
            "last_observation_status": "None",
            "last_observation_reason": "None",
            "last_observation_requires_replan": False,
            "last_observation_turn_id": 0,
            "last_observation_work_id": "None",
            "last_observation_source_action": "None",
            "last_observation_source_args": {},
            "last_observation_observed_at": "None",
            "last_observation_freshness": "None",
            "last_observation_stale_at_turn_id": 0,
            "last_attachment_delivery": {},
            "last_attachment_delivery_summary": "None",
            "last_attachment_delivery_status": "None",
            "last_attachment_delivery_requested_count": 0,
            "last_attachment_delivery_resolved_count": 0,
            "last_attachment_delivery_prepared_count": 0,
            "last_attachment_delivery_sent_count": 0,
            "last_attachment_delivery_error_count": 0,
            "last_attachment_delivery_confirmed": False,
            "turn_id": 0,
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
        self.tool_health: Dict[str, str] = {} # tool_name -> HEALTHY | DEGRADED | UNAVAILABLE
        self.tool_failure_counts: Dict[str, int] = {} # tool_name -> continuous failure count
        self.memory: List[Dict[str, Any]] = [] # Session-scope memory (accepted)
        self.candidate_store: List[Dict[str, Any]] = [] # Worker-proposed candidates
        self.decision_traces: List[Dict[str, Any]] = [] # Refined Phase 7 structured tracing
        self.event_timeline: List[Dict[str, Any]] = [] # Holistic session event log
        self.rejected_memory: List[Dict[str, Any]] = [] # Audit store for memory governance
        self.audit_trail: List[Dict[str, Any]] = [] # Auditable ledger of admin changes
        self._max_trace_history = 50
        self.cognitive_state: Dict[str, Any] = default_cognitive_state_dict()
        self.thoughts: List[Dict[str, Any]] = [] # Dedicated audit trail for cognitive thoughts
        self.media_cards: List[Dict[str, Any]] = [] # Dedicated persistence layer for UI widgets/cards
        self.last_cognitive_projection: Optional[Dict[str, Any]] = None
        self.cognitive_diagnostics: Optional[Dict[str, Any]] = None
        
        # Phase 15: Lightweight persistent snapshot of the last active frame
        self.last_cognitive_frame_snapshot: Optional[Dict[str, Any]] = None
        
        # Phase 16: Intent Agenda for tracking open loops
        self.intent_agenda = IntentAgenda()

    @staticmethod
    def _clip_anchor_text(value: Any, limit: int = 240) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip()

    def get_continuity_anchor(self) -> Dict[str, Any]:
        anchor = self.context.get("continuity_anchor")
        return dict(anchor) if isinstance(anchor, dict) else {}

    def update_continuity_anchor(
        self,
        *,
        user_input: str = "",
        objective_override: Optional[str] = None,
        objective_state: Optional[str] = None,
        last_turn_kind: Optional[str] = None,
        last_outcome_type: Optional[str] = None,
        last_action_id: Optional[str] = None,
        last_action_status: Optional[str] = None,
        last_clarification: Optional[Dict[str, Any]] = None,
        location_payload: Optional[Dict[str, Any]] = None,
        final_response: str = "",
    ) -> Dict[str, Any]:
        anchor = self.get_continuity_anchor()
        raw_user_input = self._clip_anchor_text(user_input, 320)
        if raw_user_input:
            anchor["last_user_input"] = raw_user_input
            if not anchor.get("initial_user_input"):
                anchor["initial_user_input"] = raw_user_input

        if objective_override:
            anchor["objective"] = self._clip_anchor_text(objective_override, 240)
            if raw_user_input:
                anchor["last_substantive_user_input"] = raw_user_input
        elif not anchor.get("objective"):
            goal = self._clip_anchor_text(self.state_summary.get("goal"), 240)
            if goal and goal.lower() != "standby":
                anchor["objective"] = goal

        if objective_state:
            anchor["objective_state"] = str(objective_state).strip().lower()

        if last_turn_kind:
            anchor["last_turn_kind"] = str(last_turn_kind).strip().lower()
        if last_outcome_type:
            anchor["last_outcome_type"] = self._clip_anchor_text(last_outcome_type, 80)
        if last_action_id:
            anchor["last_action_id"] = self._clip_anchor_text(last_action_id, 80)
        if last_action_status:
            anchor["last_action_status"] = self._clip_anchor_text(last_action_status, 40)
        if final_response:
            anchor["last_response"] = self._clip_anchor_text(final_response, 240)

        if isinstance(last_clarification, dict):
            anchor["last_clarification"] = {
                key: self._clip_anchor_text(value, 240) if isinstance(value, str) else value
                for key, value in last_clarification.items()
                if value not in (None, "", [], {})
            }

        if isinstance(location_payload, dict):
            location_snapshot = {}
            for key in ("source", "mode", "city", "state", "country", "timezone", "language"):
                value = location_payload.get(key)
                if value not in (None, "", [], {}):
                    location_snapshot[key] = value
            if location_snapshot:
                anchor["location"] = location_snapshot

        anchor["task_state"] = {
            "goal": self._clip_anchor_text(self.state_summary.get("goal"), 240),
            "cursor": self._clip_anchor_text(self.state_summary.get("cursor"), 80),
            "last_outcome": self._clip_anchor_text(self.state_summary.get("last_outcome"), 240),
            "last_error": self._clip_anchor_text(self.state_summary.get("last_error"), 240),
        }
        anchor["pending_action_present"] = bool(self.pending_action)
        anchor["active_focus_task_id"] = self.active_focus_task_id
        anchor["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.context["continuity_anchor"] = anchor
        return anchor

    def add_message(
        self,
        role: str,
        content: str,
        file: Optional[Dict] = None,
        attachments: Optional[List[Dict]] = None,
        msg_type: str = "default",
        summary: str = None,
        work_id: str = None,
        silent: bool = False,
        actor: Optional[Dict[str, Any]] = None,
        model_info: Optional[str] = None,
        attachment_delivery: Optional[Dict[str, Any]] = None,
        reply_to_message_id: Optional[str] = None,
    ):
        # Rough token estimation (chars / 4)
        tokens = len(content) // 4
        from zoneinfo import ZoneInfo
        tz_name = ConfigManager().get_timezone()
        try:
            timestamp = datetime.datetime.now(ZoneInfo(tz_name)).isoformat()
        except Exception:
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        msg = {
            "id": str(uuid.uuid4()),
            "role": role, 
            "content": content, 
            "tokens": tokens, 
            "type": msg_type,
            "timestamp": timestamp,
            "is_read": role == "user", # Agent "reads" user messages immediately
            "model_info": model_info
        }
        if work_id:
            msg["work_id"] = work_id
        if reply_to_message_id:
            msg["reply_to_message_id"] = str(reply_to_message_id)
        if actor and isinstance(actor, dict):
            msg["actor"] = actor
            
        if summary:
            msg["summary"] = summary
            # When summary is present, LLM context should focus on summary
            msg["tokens"] = len(summary) // 4
            
        if file:
            msg["file"] = file
        if attachments:
            msg["attachments"] = attachments
        if isinstance(attachment_delivery, dict) and attachment_delivery:
            msg["attachment_delivery"] = attachment_delivery
            
        # Back-link this message_id to any thoughts that share this work_id
        if role == "assistant" and work_id:
            for t in self.thoughts:
                if t.get("work_id") == work_id and not t.get("message_id"):
                    t["message_id"] = msg["id"]
                    
        self.history.append(msg)
        self.turn_id += 1 # Advance turn counter
        self.last_interaction = time.time()

        if isinstance(self.state_summary, dict):
            self.state_summary["turn_id"] = self.turn_id
            if role == SESSION_TYPE_USER and self.state_summary.get("last_observation_turn_id"):
                self.state_summary["last_observation_freshness"] = "stale"
                self.state_summary["last_observation_stale_at_turn_id"] = self.turn_id
            if role == SESSION_TYPE_USER and self.state_summary.get("last_attachment_delivery_status") not in (None, "", "None", "none", "stale"):
                self.state_summary["last_attachment_delivery_status"] = "stale"
                self.state_summary["last_attachment_delivery_confirmed"] = False

        if not silent and self.session_type != SESSION_TYPE_SYSTEM:
            event = {
                "type": "message_added",
                "session_id": self.session_id,
                "role": role,
                "message": msg,
                "msg_type": msg_type,
                "work_id": work_id,
                "unread_count": self.get_unread_count("assistant"),
                "payload": {
                    **msg,
                    "message_id": msg["id"],
                    "role": role,
                    "msg_type": msg_type,
                    "work_id": work_id,
                    "unread_count": self.get_unread_count("assistant"),
                },
                "channel": self.source,
                "interface": self.source,
                "source": "session",
            }
            try:
                from core.session_event_pipeline import record_session_event

                record_session_event(
                    self,
                    event,
                    defaults={
                        "session_id": self.session_id,
                        "channel": self.source,
                        "interface": self.source,
                        "source": "session",
                        "turn_id": self.turn_id,
                        "message_id": msg["id"],
                        "reply_to_message_id": reply_to_message_id,
                    },
                    publish=True,
                )
            except Exception:
                # Fallback to the legacy bus path if the pipeline cannot be loaded.
                global_event_bus.emit_threadsafe(event)

        return msg

    def add_thought(self, thought_text: str, work_id: Optional[str] = None, message_id: Optional[str] = None):
        """Adds a cognitive thought to the dedicated audit trail."""
        thought_entry = {
            "id": str(uuid.uuid4()),
            "message_id": message_id,
            "work_id": work_id,
            "thought": thought_text,
            "timestamp": time.time()
        }
        self.thoughts.append(thought_entry)
        
        # Emit event for real-time thought syncing in the dashboard
        global_event_bus.emit_threadsafe({
            "type": "cognitive_thought",
            "session_id": self.session_id,
            "thought": thought_entry
        })

    def add_media_card(self, card_data: Dict[str, Any]) -> str:
        """
        Adds a new media/UI card snapshot to the session's persistence layer.
        card_data should contain 'id', 'type', 'payload', 'timestamp', etc.
        """
        if not isinstance(card_data, dict):
            return ""
            
        card_id = card_data.get("id") or f"media_{int(time.time() * 1000)}_{str(uuid.uuid4())[:8]}"
        card_data["id"] = card_id
        
        if "timestamp" not in card_data:
            card_data["timestamp"] = int(time.time() * 1000)
            
        # Check if card with same ID exists and update it, otherwise append
        existing = next((c for c in getattr(self, "media_cards", []) if c.get("id") == card_id), None)
        if existing:
            existing.update(card_data)
        else:
            if not hasattr(self, "media_cards"):
                self.media_cards = []
            self.media_cards.append(card_data)
            
        return card_id

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

    def apply_memory_patch(self, memory_id: str, patch: dict, author: str, reason: str):
        """Applies a patch to a memory entry. Tombstone-based 'deletion' is patch: {'is_deleted': True}."""
        for entry in self.memory:
            if entry.get("memory_id") == memory_id or entry.get("id") == memory_id:
                old_value = entry.copy()
                entry.update(patch)
                if "memory_id" not in entry and entry.get("id"):
                    entry["memory_id"] = entry["id"]
                self.audit_trail.append({
                    "ts": time.time(),
                    "type": "memory_patch",
                    "id": memory_id,
                    "author": author,
                    "reason": reason,
                    "old_value": old_value,
                    "new_value": entry.copy()
                })
                return True
        return False

    def get_unread_count(self, role: str = "assistant") -> int:
        """Returns the number of unread messages from a specific role."""
        return sum(1 for msg in self.history if msg.get("role") == role and not msg.get("is_read", False))

    def clear_history(self):
        self.history = []

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "source": self.source,
            "session_type": self.session_type,
            "domain": self.domain,
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
            "candidate_store": self.candidate_store,
            "decision_traces": self.decision_traces,
            "event_timeline": self.event_timeline,
            "rejected_memory": self.rejected_memory,
            "audit_trail": self.audit_trail,
            "tool_health": self.tool_health,
            "tool_failure_counts": self.tool_failure_counts,
            "cognitive_state": self.cognitive_state,
            "last_cognitive_projection": self.last_cognitive_projection,
            "cognitive_diagnostics": self.cognitive_diagnostics,
            "last_cognitive_frame_snapshot": self.last_cognitive_frame_snapshot,
            "intent_agenda": self.intent_agenda.to_dict(),
            "media_cards": getattr(self, "media_cards", [])
        }

    @classmethod
    def from_dict(cls, data: Dict):
        session = cls(
            data["session_id"], 
            data.get("source", "web"), 
            data.get("session_type", SESSION_TYPE_USER),
            domain=data.get("domain")
        )
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
                tz = ConfigManager().get_timezone()
                # Simplified: for legacy, just use UTC or system local but aware
                from zoneinfo import ZoneInfo
                try:
                    msg["timestamp"] = datetime.datetime.now(ZoneInfo(tz)).isoformat()
                except Exception:
                    msg["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
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
            "last_observation": "None",
            "last_observation_evidence": "None",
            "last_observation_evidence_count": 0,
            "last_observation_evidence_shown": 0,
            "last_observation_evidence_truncated": False,
            "last_observation_status": "None",
            "last_observation_reason": "None",
            "last_observation_requires_replan": False,
            "last_observation_turn_id": 0,
            "last_observation_work_id": "None",
            "last_observation_source_action": "None",
            "last_observation_source_args": {},
            "last_observation_observed_at": "None",
            "last_observation_freshness": "None",
            "last_observation_stale_at_turn_id": 0,
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
        session.decision_traces = data.get("decision_traces", [])
        session.event_timeline = data.get("event_timeline", [])
        session.rejected_memory = data.get("rejected_memory", [])
        session.audit_trail = data.get("audit_trail", [])
        session.tool_health = data.get("tool_health", {})
        session.tool_failure_counts = data.get("tool_failure_counts", {})
        session.cognitive_state = data.get("cognitive_state", default_cognitive_state_dict())
        session.last_cognitive_projection = data.get("last_cognitive_projection")
        session.cognitive_diagnostics = data.get("cognitive_diagnostics")
        session.last_cognitive_frame_snapshot = data.get("last_cognitive_frame_snapshot")
        session.media_cards = data.get("media_cards", [])
        if "intent_agenda" in data:
            session.intent_agenda = IntentAgenda.from_dict(data["intent_agenda"])
        return session

    def publish_event(self, event: Dict[str, Any]):
        """Publishes a Worker event to the session inbox with deduplication and ring buffer."""
        # Ensure mandatory metadata
        if "event_id" not in event:
            event["event_id"] = str(uuid.uuid4())
        if "timestamp" not in event:
            event["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        event_id = event.get("event_id")
        e_type = str(event.get("event_type") or "").upper()

        # Deduplicate
        if any(e.get("event_id") == event_id for e in self.event_history):
            return

        # Divert MEMORY_CANDIDATE to candidate_store
        if e_type == "MEMORY_CANDIDATE":
            if any(e.get("memory_id") == event.get("memory_id") for e in self.candidate_store):
                return
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
                self.task_registry[task_id] = {
                    "task_id": task_id,
                    "task_role": event.get("task_role", "unknown task"),
                    "status": e_type,
                    "turn_id": event.get("turn_id", self.turn_id),
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
                    "last_outcome": event.get("outcome", ""),
                    "origin_type": event.get("origin_type", "system"),
                    "parent_task_id": event.get("parent_task_id"),
                    "spawn_reason": event.get("spawn_reason", "user_request"),
                    "priority_level": event.get("priority_level"),
                    "urgency": event.get("urgency", 0.0),
                    "attention_score": event.get("attention_score", 0.0),
                    "user_waiting": event.get("user_waiting", False),
                    "depends_on": event.get("depends_on", []),
                    "blocks": event.get("blocks", []),
                    "timeline": [] # Phase 7: Task-specific timeline
                }
                # Add initial event to timeline
                self._add_to_task_timeline(task_id, event)
            else:
                # Update
                task = self.task_registry[task_id]
                task["status"] = e_type
                task["last_event_at"] = time.time()
                task["turn_id"] = event.get("turn_id", task.get("turn_id", self.turn_id))
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
                
                # Phase 10: Store checkpoint and completion summary
                if event.get("checkpoint"):
                    task["checkpoint"] = event["checkpoint"]
                if event.get("completion_summary"):
                    task["completion_summary"] = event["completion_summary"]
                
                # Phase 11: Task Scheduling Metadata
                if event.get("priority_level"):
                    task["priority_level"] = event["priority_level"]
                if event.get("urgency") is not None:
                    task["urgency"] = event["urgency"]
                if event.get("attention_score") is not None:
                    task["attention_score"] = event["attention_score"]
                if "user_waiting" in event:
                    task["user_waiting"] = event["user_waiting"]
                if event.get("depends_on"):
                    task["depends_on"] = event["depends_on"]
                if event.get("blocks"):
                    task["blocks"] = event["blocks"]
                
                # Phase 7: Update timeline
                self._add_to_task_timeline(task_id, event)

    def _add_to_task_timeline(self, task_id: str, event: Dict[str, Any]):
        """Helper to record task-specific lifecycle events."""
        task = self.task_registry.get(task_id)
        if not task:
            return
            
        if "timeline" not in task:
            task["timeline"] = []
            
        timeline_entry = {
            "event_id": event.get("event_id") or str(uuid.uuid4()),
            "timestamp": event.get("timestamp") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "type": str(event.get("event_type") or "PROGRESS").upper(),
            "delta": {k: v for k, v in event.items() if k not in {"event_id", "timestamp", "task_id", "event_type"}},
            "user_visible": task.get("user_visible", False)
        }
        
        # Link to current decision trace if one exists for this turn
        if hasattr(self, "decision_traces") and self.decision_traces:
            # Heuristic: the last trace in the same turn
            last_trace = self.decision_traces[-1]
            if last_trace.get("turn_id") == self.turn_id:
                timeline_entry["trace_id"] = last_trace.get("trace_id")
                
        task["timeline"].append(timeline_entry)
        
        # Also log to session-level event_timeline
        if not hasattr(self, "event_timeline"):
            self.event_timeline = []
        self.event_timeline.append({
            "scope": "TASK",
            "task_id": task_id,
            "event_id": timeline_entry["event_id"],
            "timestamp": timeline_entry["timestamp"],
            "type": timeline_entry["type"]
        })

    def drain_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Drains the earliest N events from the history (FIFO)."""
        drained = self.event_history[:limit]
        self.event_history = self.event_history[limit:]
        return drained

    def get_cognitive_frame(self, user_input: str = "") -> CognitiveFrame:
        """Dynamically generates the current Cognitive Frame from session truth."""
        frame = build_cognitive_frame(self, user_input)
        # Store lightweight snapshot for observability
        self.last_cognitive_frame_snapshot = {
            "objective": frame.objective,
            "context_sources": frame.context_sources,
            "timestamp": frame.timestamp
        }
        return frame

    def get_context_for_llm(self, limit_tokens: int = 6000, limit_msgs: int = 30) -> List[Dict[str, Any]]:
        """Returns the compressed conversation context within bounds."""
        context = []
        total_tokens = 0
        
        # Iterate backwards through history
        # Phase 15: Aggressive Context Compression Strategy
        recent_threshold = 5 # Strict raw limit for recent turns
        turns_added = 0
        
        for msg in reversed(self.history):
            content_str = str(msg.get("content", ""))
            tokens_val = msg.get("tokens")
            if tokens_val is None:
                msg_tokens = len(content_str) // 4
            else:
                msg_tokens = int(tokens_val)

            if total_tokens + msg_tokens > limit_tokens or len(context) >= limit_msgs:
                break
            
            clean_role = str(msg.get("role", "user"))
            actor = msg.get("actor") if isinstance(msg.get("actor"), dict) else {}
            actor_label = str(actor.get("display_name") or actor.get("name") or actor.get("id") or "").strip()
            actor_kind = str(actor.get("kind") or "").strip().lower()
            is_recent = turns_added < recent_threshold
            
            # Demotion Rule: System observations older than recent threshold are discarded 
            # (they are already captured in task_registry state/summaries)
            if not is_recent and clean_role == "system" and not (msg.get("file") or msg.get("attachments")):
                continue

            # Stubbornness / Error Pruning: Remove stale assistant errors and repetitive credential requests
            if not is_recent and clean_role == "assistant":
                txt_lower = content_str.lower()
                error_markers = [
                    "preciso saber qual serviço",
                    "preciso de algumas informações",
                    "para verificar sua",
                    "planning failed",
                    "admission_reject",
                    "session_busy",
                    "session already has a running",
                    "lidar com uma tarefa",
                ]
                if any(m in txt_lower for m in error_markers):
                    continue

            # Preferences: Use summary if older than recent threshold, else content
            if is_recent:
                llm_content = content_str
            else:
                summary_str = msg.get("summary")
                llm_content = str(summary_str) if summary_str else content_str
                # Add demotion label prefix
                if llm_content and not llm_content.startswith("[COMPRESSED"):
                    llm_content = f"[COMPRESSED TURN]: {llm_content}"
            
            if clean_role == "system":
                clean_role = "user"
                llm_content = f"[SYSTEM/OBSERVATION]:\n{llm_content}"
            elif clean_role not in {"user", "assistant"}:
                # Multi-role compatibility layer: preserve role semantics as prefixed content
                # while mapping to user role for downstream model APIs.
                clean_role = "user"
                role_tag = str(msg.get("role") or "event").upper()
                llm_content = f"[ROLE:{role_tag}]:\n{llm_content}"

            # Distinguish multi-user/group actors without forcing everything into a single "user" identity.
            if clean_role == "user" and actor_kind in {"group_participant", "participant", "human_user"} and actor_label:
                llm_content = f"[FROM:{actor_label}]\n{llm_content}"
                
            clean_msg: Dict[str, Any] = {"role": clean_role, "content": llm_content}
            
            if "attachments" in msg:
                clean_msg["attachments"] = msg["attachments"]
            if "file" in msg:
                clean_msg["file"] = msg["file"]
                
            context.insert(0, clean_msg)
            turns_added += 1
            total_tokens += msg_tokens
            turns_added += 1
            
        return context
