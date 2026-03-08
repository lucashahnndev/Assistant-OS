import uuid
import datetime
from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, field_validator

class WorkerEventType(str, Enum):
    STARTED = "STARTED"
    PROGRESS = "PROGRESS"
    SLOW = "SLOW"
    STALLED = "STALLED"
    WAITING_INPUT = "WAITING_INPUT"
    RECOVERY_NEEDED = "RECOVERY_NEEDED"
    DEGRADED_EXECUTION = "DEGRADED_EXECUTION"
    ATTENTION_REQUIRED = "ATTENTION_REQUIRED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    MEMORY_CANDIDATE = "MEMORY_CANDIDATE"
    CHECKPOINT = "CHECKPOINT"
    SCHEDULING_UPDATE = "SCHEDULING_UPDATE"

class AttentionLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class TaskOrigin(str, Enum):
    USER = "user"
    SUPERVISOR = "supervisor"
    SYSTEM = "system"
    TASK = "task" # Derived from another task

class TaskSpawnReason(str, Enum):
    USER_REQUEST = "user_request"
    PLAN_STEP = "plan_step"
    RECOVERY = "recovery"
    PROACTIVE = "proactive"
    SUBTASK = "subtask"

class WorkerEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    
    # Task context
    task_id: str
    run_id: str
    task_role: str
    intent_group_id: Optional[str] = None
    
    # Task-Centric Phase 7.1 metadata
    origin_type: TaskOrigin = TaskOrigin.SYSTEM
    parent_task_id: Optional[str] = None
    spawn_reason: TaskSpawnReason = TaskSpawnReason.USER_REQUEST
    
    # Flow control (anti-"reply from the past")
    turn_id: int
    base_turn_id: int
    
    # State update
    event_type: WorkerEventType
    phase: str
    progress: float = Field(ge=0.0, le=1.0)
    summary: str
    
    # Detailed feedback
    error_code: Optional[str] = None
    failure_summary: Optional[str] = None
    needs_user_input: bool = False
    suggested_user_prompt: Optional[str] = None
    attention_level: AttentionLevel = AttentionLevel.LOW
    
    # Structured outputs
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)

    # Phase 10: Checkpointing & Structured Summaries
    checkpoint: Optional[Dict[str, Any]] = None
    completion_summary: Optional[Dict[str, Any]] = None

    # Phase 11: Cognitive Scheduling
    priority_level: Optional[str] = None # low, medium, high, critical
    urgency: Optional[float] = None      # 0.0 to 1.0
    attention_score: Optional[float] = None
    user_waiting: bool = False
    depends_on: List[str] = Field(default_factory=list)
    blocks: List[str] = Field(default_factory=list)

    @field_validator('timestamp')
    @classmethod
    def validate_iso8601(cls, v: str) -> str:
        try:
            datetime.datetime.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError("timestamp must be in ISO8601 format")

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

class MemoryEntry(BaseModel):
    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: str # preference, fact, task_outcome, unresolved_item, summary
    scope: str # task, session, global
    source_type: str # worker, supervisor, system
    source_id: str
    content: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: str = "candidate"
    approved_by: Optional[str] = None
    reason: Optional[str] = None
    dedupe_key: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    ttl: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
