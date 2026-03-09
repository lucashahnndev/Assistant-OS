import time
import uuid
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("Cognition")

@dataclass
class CognitiveFrame:
    """
    Ephemerally reconstructed Cognitive Frame for the current reasoning turn.
    This defines the layers of context prioritization.
    """
    objective: str = "Standby"
    primary_task: Optional[Dict[str, Any]] = None
    secondary_tasks: List[Dict[str, Any]] = field(default_factory=list)
    active_intents: List[Dict[str, Any]] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    active_user_intent: str = "unknown"
    reasoning_mode: str = "standard"
    context_sources: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "primary_task": self.primary_task,
            "secondary_tasks": self.secondary_tasks,
            "active_intents": self.active_intents,
            "blockers": self.blockers,
            "constraints": self.constraints,
            "active_user_intent": self.active_user_intent,
            "reasoning_mode": self.reasoning_mode,
            "context_sources": self.context_sources,
            "timestamp": self.timestamp
        }

def build_cognitive_frame(session: Any, user_input: str = "") -> CognitiveFrame:
    """
    Dynamically rebuilds the Cognitive Frame from the session's active state.
    Produces the layered priority structure (Foreground/Background/Demoted).
    """
    frame = CognitiveFrame()
    frame.context_sources.append("runtime_state")

    # 1. Objective Parsing
    # Look at active intent group or session state summary
    frame.objective = session.state_summary.get("goal", "Standby")
    if user_input:
        frame.active_user_intent = "user_prompt"
        frame.context_sources.append("user_input")

    # 2. Task Layering (Primary vs Secondary)
    # Tasks are categorized by focus and status
    active_focus_id = session.active_focus_task_id
    running_background = []
    
    for task_id, task in session.task_registry.items():
        status = task.get("status", "").upper()
        # DEMOTION / DISCARD:
        # If COMPLETED, FAILED, or SUPERSEDED, it leaves the active context unless it's strictly the primary focus *this turn*
        is_terminal = status in {"COMPLETED", "FAILED", "SUPERSEDED"}
        
        # Build lightweight task representation for the LLM
        # Compress the history/timeline
        task_snippet = {
            "task_id": task_id,
            "role": task.get("task_role"),
            "status": status,
            "summary": task.get("last_summary") or task.get("completion_summary") or "",
            "priority": task.get("priority_level"),
            "waiting_user": task.get("waiting_user_response", False)
        }

        if task_id == active_focus_id and not is_terminal:
            frame.primary_task = task_snippet
            frame.context_sources.append("primary_task")
        elif not is_terminal and status in {"STARTED", "PROGRESS", "PAUSED", "BLOCKED_BY_DEPENDENCY", "FOREGROUND_BUDGET_EXCEEDED"}:
            running_background.append(task_snippet)
            
    # If no primary task but there are running background tasks, maybe promote one or leave empty
    frame.secondary_tasks = running_background
    if running_background:
        frame.context_sources.append("secondary_tasks")

    # Phase 16: Intent Tracking
    if hasattr(session, "intent_agenda"):
        active_intents = session.intent_agenda.get_active_intents()
        for i in active_intents:
            frame.active_intents.append(i.to_dict())
            if i.status == "PAUSED" and i.blocking_reason:
                frame.blockers.append(f"Intent blocked: {i.summary} (Reason: {i.blocking_reason})")
        if active_intents:
            frame.context_sources.append("active_intents")

    # 3. Blockers
    # Identify systemic or task-level blockages
    for t in session.task_registry.values():
        if t.get("waiting_user_response"):
            frame.blockers.append(f"Task '{t.get('task_role')}' is waiting for user response.")
        if t.get("status") == "BLOCKED_BY_DEPENDENCY":
            deps = t.get("depends_on", [])
            frame.blockers.append(f"Task '{t.get('task_role')}' blocked by dependencies: {deps}.")
            
    # 4. Constraints
    # Identify tool degradation or safe-mode overrides
    if hasattr(session, "tool_health"):
        for tool_name, health in session.tool_health.items():
            if health != "HEALTHY":
                frame.constraints.append(f"Tool '{tool_name}' is {health}.")
                frame.context_sources.append("tool_health")
                
    # Optional constraint: Token budgets / turn limits
    # ...

    return frame
