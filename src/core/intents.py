import time
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class Intent:
    intent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    intent_type: str = "general" # e.g., conversational, long_running_task
    summary: str = ""
    status: str = "OPEN" # OPEN, PAUSED, RESOLVED, ABANDONED
    linked_task_ids: List[str] = field(default_factory=list) # Optional, 0-N tasks
    blocking_reason: Optional[str] = None # Why is this PAUSED? e.g., user_approval
    next_expected_action: Optional[str] = None # What unblocks this?
    last_updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "intent_type": self.intent_type,
            "summary": self.summary,
            "status": self.status,
            "linked_task_ids": self.linked_task_ids,
            "blocking_reason": self.blocking_reason,
            "next_expected_action": self.next_expected_action,
            "last_updated_at": self.last_updated_at
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Intent":
        return cls(
            intent_id=data.get("intent_id", str(uuid.uuid4())),
            intent_type=data.get("intent_type", "general"),
            summary=data.get("summary", ""),
            status=data.get("status", "OPEN"),
            linked_task_ids=data.get("linked_task_ids", []),
            blocking_reason=data.get("blocking_reason"),
            next_expected_action=data.get("next_expected_action"),
            last_updated_at=data.get("last_updated_at", time.time())
        )

class IntentAgenda:
    """
    Persistent tracker of high-level open goals and unresolved objectives.
    Remains cognitively lightweight and avoids duplicating full task lifecycle state.
    """
    def __init__(self):
        self.intents: Dict[str, Intent] = {}

    def add_intent(self, summary: str, intent_type: str = "general", linked_task_ids: Optional[List[str]] = None) -> Intent:
        intent = Intent(
            intent_type=intent_type,
            summary=summary,
            linked_task_ids=linked_task_ids or []
        )
        self.intents[intent.intent_id] = intent
        return intent

    def get_intent(self, intent_id: str) -> Optional[Intent]:
        return self.intents.get(intent_id)

    def update_intent_status(self, intent_id: str, status: str, blocking_reason: Optional[str] = None, next_expected_action: Optional[str] = None) -> bool:
        """
        Updates an intent's status (OPEN, PAUSED, RESOLVED, ABANDONED).
        When pausing, it is recommended to provide a blocking_reason and next_expected_action.
        """
        intent = self.intents.get(intent_id)
        if not intent:
            return False
        
        intent.status = status
        intent.blocking_reason = blocking_reason
        intent.next_expected_action = next_expected_action
        intent.last_updated_at = time.time()
        return True

    def link_task_to_intent(self, intent_id: str, task_id: str) -> bool:
        """Associates an execution task with an open intent."""
        intent = self.intents.get(intent_id)
        if not intent:
            return False
            
        if task_id not in intent.linked_task_ids:
            intent.linked_task_ids.append(task_id)
            intent.last_updated_at = time.time()
        return True

    def get_active_intents(self) -> List[Intent]:
        """Returns only OPEN and PAUSED intents for cognitive frame inclusion."""
        return [intent for intent in self.intents.values() if intent.status in {"OPEN", "PAUSED"}]

    def evaluate_reentry_signals(self, task_registry: Dict[str, Any]) -> None:
        """
        Conservative re-entry logic. Un-pauses an intent if its blocking dependencies
        (e.g., tasks) have completed successfully.
        """
        for intent in self.intents.values():
            if intent.status == "PAUSED" and intent.linked_task_ids:
                # Conservative rule: only explicit completion reopens the intent.
                # A superseded task may have been replaced, not actually resolved.
                all_tasks_completed = True
                has_valid_tasks = False
                
                for tid in intent.linked_task_ids:
                    task = task_registry.get(tid)
                    if task:
                        has_valid_tasks = True
                        if task.get("status") != "COMPLETED":
                            all_tasks_completed = False
                            break
                            
                if has_valid_tasks and all_tasks_completed:
                    self.update_intent_status(intent.intent_id, "OPEN")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intents": {uid: intent.to_dict() for uid, intent in self.intents.items()}
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentAgenda":
        agenda = cls()
        intents_data = data.get("intents", {})
        for uid, idata in intents_data.items():
            agenda.intents[uid] = Intent.from_dict(idata)
        return agenda
