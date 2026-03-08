import logging
from typing import Any, Dict, List, Optional, Tuple, cast
from enum import Enum
from .errors import ErrorCode, ErrorCategory

logger = logging.getLogger("SupervisorPolicy")

class SupervisorOutcome(str, Enum):
    CHAT = "CHAT"
    PANEL = "PANEL"
    INPUT = "INPUT"
    SILENT = "SILENT"

class ExecutionRecommendation(str, Enum):
    RETRY = "RETRY"            # Transient failure, try again with backoff
    FALLBACK = "FALLBACK"      # Action failed, try alternative tool/method
    ESCALATE = "ESCALATE"      # Permission or logic blocker, ask user
    REPLAN = "REPLAN"          # Significant failure, needs new plan
    CANCEL = "CANCEL"          # Irrecoverable or superseded
    IGNORE = "IGNORE"          # Minor notification, no intervention needed

class ExecutionAssessment:
    def __init__(
        self,
        recommendation: ExecutionRecommendation,
        reason: str,
        severity: str = "medium",
        suggested_delay: float = 0.0,
        fallback_action: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.recommendation = recommendation
        self.reason = reason
        self.severity = severity
        self.suggested_delay = suggested_delay
        self.fallback_action = fallback_action
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation": self.recommendation.value,
            "reason": self.reason,
            "severity": self.severity,
            "suggested_delay": self.suggested_delay,
            "fallback_action": self.fallback_action,
            "metadata": self.metadata
        }

class SupervisorPolicy:
    """
    Deterministic behavioral policy for the Supervisor (AgentOrchestrator).
    Consolidates scoring, focus shifting, and event visibility rules.
    """

    # Priority mapping for tie-breaks
    PRIORITY_MAP = {
        "WAITING_INPUT": 5,
        "FAILED": 4,
        "COMPLETED": 3,
        "STALLED": 2.5,
        "RECOVERY_NEEDED": 2.2,
        "DEGRADED_EXECUTION": 2.1,
        "SLOW": 2,
        "PROGRESS": 1,
        "UNKNOWN": 0
    }

    # Scoring Weights
    WEIGHT_FOCUS = 50
    WEIGHT_WAITING_INPUT = 30
    WEIGHT_COMPLETED = 25
    WEIGHT_FAILED = 20
    PENALTY_STALENESS_PER_TURN = 5

    # Thresholds
    STALE_TURN_DISTANCE = 1
    CHAT_CAPPING_LIMIT = 2
    LOOP_DETECTION_THRESHOLD = 4
    FAILURE_LOOP_THRESHOLD = 3

    # Recovery Configs
    RETRY_CONFIG = {
        "max_attempts": 3,
        "base_delay_s": 2.0,
        "multiplier": 2.0,
        "max_retries_per_task": 2,
        "max_retries_per_tool": 3,
        "max_fallback_depth_per_task": 2
    }

    FALLBACK_MAP = {
        "browser_click": "keyboard_tab_enter",
        "search_web": "read_url_content", # If search fails, maybe direct read helps
    }
    
    CAPABILITY_FALLBACK_MAP = {
        "retrieval": ["search_web", "read_url_content", "wikipedia_search"],
        "navigation": ["browser_navigate", "browser_click", "keyboard_tab_enter"],
        "filesystem": ["list_dir", "view_file", "grep_search"],
    }

    CIRCUIT_BREAKER_CONFIG = {
        "degraded_threshold": 2,    # failures in a row
        "unavailable_threshold": 4, # failures in a row
        "reset_timeout_s": 300      # 5 minutes
    }

    CHECKPOINT_CONFIG = {
        "auto_checkpoint_interval_s": 600,  # 10 minutes
        "max_checkpoints_per_task": 50,
        "phase_change_checkpoint": True     # Force checkpoint on phase shift
    }

    SCHEDULING_CONFIG = {
        "max_foreground_tasks": 1,
        "priority_weights": {
            "critical": 100,
            "high": 50,
            "medium": 20,
            "low": 0
        }
    }

    @classmethod
    def evaluate_scheduling(
        cls,
        tasks: Dict[str, Dict[str, Any]],
        active_focus_task_id: Optional[str] = None,
        current_turn_id: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Ranks tasks and suggests scheduling transitions (RUNNING, BACKGROUND, PAUSED).
        Returns a list of suggested updates: [{"task_id": "...", "suggested_state": "..."}]
        """
        suggestions: List[Dict[str, Any]] = []
        
        # 1. Collect candidate tasks (exclude COMPLETED/FAILED)
        candidates: List[Dict[str, Any]] = []
        config = getattr(cls, "SCHEDULING_CONFIG", {})
        if not isinstance(config, dict):
            config = {}
            
        weights_val = config.get("priority_weights")
        weights: Dict[str, int] = weights_val if isinstance(weights_val, dict) else {}
        
        for tid, t in tasks.items():
            if not isinstance(t, dict):
                continue
            status = str(t.get("status", ""))
            if status in {"COMPLETED", "FAILED"}:
                continue
            
            # Calculate base score
            p_level = str(t.get("priority_level", "low"))
            priority_score = int(cast(Dict[str, int], weights).get(p_level, 0))
            
            urgency_raw = t.get("urgency", 0.0)
            urgency = float(str(urgency_raw)) if urgency_raw is not None else 0.0
            urgency *= 50
            
            attention = 30 if tid == active_focus_task_id else 0
            user_waiting_flag = bool(t.get("user_waiting", False))
            user_waiting_score = 40 if user_waiting_flag else 0
            
            score = float(priority_score) + urgency + float(attention) + float(user_waiting_score)
            
            # Tie-break fields (Phase 11 Refinement)
            # 1) user_waiting = true wins
            # 2) current focus task wins
            # 3) smaller turn_distance wins
            # 4) more recent task wins (created_at)
            # 5) fallback to task_id
            
            t_turn = int(t.get("turn_id", 0))
            turn_distance = current_turn_id - t_turn
            created_at = float(t.get("created_at", 0.0))
            
            # Sorting key (tuple for deterministic ranking)
            # We use negative for 'higher is better' if sorting ascending, 
            # or positive for 'lower is better'. 
            # Since we sort descending by overall rank:
            rank_key = (
                score,
                1 if user_waiting_flag else 0,
                1 if tid == active_focus_task_id else 0,
                -turn_distance, # Smaller distance wins -> higher value
                created_at,     # Higher (more recent) wins
                tid             # Final stable string tie-break
            )
            
            candidates.append({
                "task_id": tid,
                "rank_key": rank_key,
                "status": status,
                "depends_on": t.get("depends_on") or [],
                "blocks": t.get("blocks") or []
            })
            
        # 2. Handle Dependencies (block tasks with uncompleted deps)
        eligible: List[Dict[str, Any]] = []
        for c in candidates:
            deps = c.get("depends_on")
            blocking_deps = []
            if isinstance(deps, list):
                for d in deps:
                    dep_id = str(d)
                    dep_task = tasks.get(dep_id)
                    if isinstance(dep_task, dict) and dep_task.get("status") != "COMPLETED":
                        blocking_deps.append(dep_id)
            
            if blocking_deps:
                # If currently running but blocked, suggest PAUSING
                c_status = str(c.get("status", ""))
                if c_status in {"STARTED", "PROGRESS", "RUNNING"}:
                    suggestions.append({
                        "task_id": str(c.get("task_id", "")), 
                        "suggested_state": "PAUSED", 
                        "reason": "BLOCKED_BY_DEPENDENCY",
                        "metadata": {"blocking_task": blocking_deps[0]}
                    })
                continue
            eligible.append(c)
            
        # 3. Rank Eligible Tasks
        eligible.sort(key=lambda x: x["rank_key"], reverse=True)
        
        # 4. Enforce Attention Budget (Budget for FOREGROUND/RUNNING)
        max_fg_val = config.get("max_foreground_tasks", 1)
        max_fg = int(str(max_fg_val)) if max_fg_val is not None else 1
        
        for i, c in enumerate(eligible):
            c_status = str(c.get("status", ""))
            c_id = str(c.get("task_id", ""))
            if i < max_fg:
                # Top tasks should be RUNNING
                if c_status not in {"STARTED", "PROGRESS", "RUNNING"}:
                    suggestions.append({
                        "task_id": c_id, 
                        "suggested_state": "RESUME", 
                        "reason": "PROMOTED_TO_FOREGROUND"
                    })
            else:
                # Other tasks should be BACKGROUND or PAUSED
                if c_status in {"STARTED", "PROGRESS", "RUNNING"}:
                    suggestions.append({
                        "task_id": c_id, 
                        "suggested_state": "PAUSED", 
                        "reason": "FOREGROUND_BUDGET_EXCEEDED"
                    })
                    
        return suggestions

    @classmethod
    def should_create_checkpoint(
        cls,
        last_checkpoint_timestamp: float,
        current_time: float,
        phase_changed: bool = False
    ) -> bool:
        """Determines if a new checkpoint should be created according to policy."""
        if phase_changed and cls.CHECKPOINT_CONFIG["phase_change_checkpoint"]:
            return True
            
        elapsed = current_time - last_checkpoint_timestamp
        interval = float(cls.CHECKPOINT_CONFIG["auto_checkpoint_interval_s"])
        if elapsed >= interval:
            return True
            
        return False

    @classmethod
    def evaluate_recovery(
        cls,
        task_id: str,
        error_code: ErrorCode,
        error_category: ErrorCategory,
        attempt_count: int,
        side_effect: str = "none",
        fallback_depth: int = 0,
        task_retry_count: int = 0
    ) -> ExecutionAssessment:
        """
        Produces a structured execution assessment for the Supervisor.
        This is advisory; the Supervisor makes the final decision.
        """
        # 0. Handle INVALID_REQUEST logic (User Refinement)
        # 0. High Fidelity Policy Blocks
        if error_code == ErrorCode.POLICY_BLOCKED:
            return ExecutionAssessment(
                recommendation=ExecutionRecommendation.ESCALATE,
                reason="Operation blocked by safety or capability policy.",
                severity="high",
                metadata={
                    "policy_code": "SAFETY_OR_CAPABILITY_LIMIT",
                    "policy_reason": "Requested action exceeds current safety or structural limits.",
                    "blocked_capability": "unknown"
                }
            )

        if error_code == ErrorCode.INVALID_REQUEST:
            return ExecutionAssessment(
                recommendation=ExecutionRecommendation.REPLAN,
                reason=f"Action failed with invalid request ({error_code.value}). Re-planning required.",
                severity="medium"
            )

        # 1. Permanent/Fatal Failure -> REPLAN or ESCALATE
        if error_category == ErrorCategory.FATAL:
            return ExecutionAssessment(
                recommendation=ExecutionRecommendation.REPLAN,
                reason=f"Action failed with fatal error {error_code.value}.",
                severity="high"
            )

        # 2. Permission Failure -> ESCALATE
        if error_category == ErrorCategory.PERMISSION:
            return ExecutionAssessment(
                recommendation=ExecutionRecommendation.ESCALATE,
                reason=f"Action blocked by permission error {error_code.value}.",
                severity="high"
            )

        # 3. Transient Failure -> RETRY (within limits + Side-Effect awareness)
        if error_category == ErrorCategory.TRANSIENT:
            # User Refinement: Don't auto-retry destructive actions
            if side_effect == "destructive":
                return ExecutionAssessment(
                    recommendation=ExecutionRecommendation.ESCALATE,
                    reason=f"Transient failure {error_code.value} on destructive action. Manual verification recommended.",
                    severity="medium"
                )

            # Phase 8.1: Check granular budgets
            if task_retry_count >= cls.RETRY_CONFIG["max_retries_per_task"]:
                return ExecutionAssessment(
                    recommendation=ExecutionRecommendation.REPLAN,
                    reason=f"Task-level retry budget exhausted ({task_retry_count}). Cascading failure prevention.",
                    severity="high"
                )

            if attempt_count < cls.RETRY_CONFIG["max_attempts"]:
                delay = cls.RETRY_CONFIG["base_delay_s"] * (cls.RETRY_CONFIG["multiplier"] ** attempt_count)
                return ExecutionAssessment(
                    recommendation=ExecutionRecommendation.RETRY,
                    reason=f"Transient failure {error_code.value}. Retrying (attempt {attempt_count+1}).",
                    suggested_delay=delay
                )
            else:
                # Max retries reached, try fallback if within depth budget
                if fallback_depth < cls.RETRY_CONFIG["max_fallback_depth_per_task"]:
                    return ExecutionAssessment(
                        recommendation=ExecutionRecommendation.FALLBACK,
                        reason=f"Max retries reached for transient error {error_code.value}.",
                        severity="high"
                    )
                else:
                    return ExecutionAssessment(
                        recommendation=ExecutionRecommendation.REPLAN,
                        reason="Max fallback depth reached.",
                        severity="high"
                    )

        # 4. Dependency Failure -> FALLBACK or REPLAN
        if error_category == ErrorCategory.DEPENDENCY:
            if fallback_depth < cls.RETRY_CONFIG["max_fallback_depth_per_task"]:
                 return ExecutionAssessment(
                    recommendation=ExecutionRecommendation.FALLBACK,
                    reason=f"Dependency issue detected: {error_code.value}.",
                    severity="high"
                )
            return ExecutionAssessment(
                recommendation=ExecutionRecommendation.REPLAN,
                reason=f"Dependency issue detected: {error_code.value} (Max fallback depth reached).",
                severity="high"
            )

        # 5. Stalled Execution -> ESCALATE (ask user or supervisor to intervene)
        if error_category == ErrorCategory.STALLED:
            return ExecutionAssessment(
                recommendation=ExecutionRecommendation.ESCALATE,
                reason="Task is stalled (no progress reported). Intervention needed.",
                severity="medium"
            )

        return ExecutionAssessment(
            recommendation=ExecutionRecommendation.REPLAN,
            reason=f"Unclassified error {error_code.value} in category {error_category.value}.",
            severity="medium"
        )

    @classmethod
    def evaluate_event(
        cls, 
        event: Dict[str, Any], 
        task: Optional[Dict[str, Any]], 
        current_turn: int
    ) -> Dict[str, Any]:
        """
        Calculates score and selects a suggested outcome for a worker event.
        """
        raw_type = event.get("event_type", "UNKNOWN")
        e_type = str(raw_type.value if hasattr(raw_type, "value") else raw_type).upper()
        
        raw_attention = event.get("attention_level", "low")
        attention = str(raw_attention.value if hasattr(raw_attention, "value") else raw_attention).lower()
        
        base_turn = event.get("base_turn_id", current_turn)
        turn_dist = current_turn - base_turn
        is_stale = turn_dist > cls.STALE_TURN_DISTANCE
        
        is_focused = bool(task and task.get("is_relevant_to_current_focus"))
        
        # 1. Scoring logic
        score = 0
        if is_focused: 
            score += cls.WEIGHT_FOCUS
            
        if e_type == "WAITING_INPUT": 
            score += cls.WEIGHT_WAITING_INPUT
        elif e_type == "COMPLETED": 
            score += cls.WEIGHT_COMPLETED
        elif e_type == "FAILED": 
            score += cls.WEIGHT_FAILED
            
        score -= (turn_dist * cls.PENALTY_STALENESS_PER_TURN)
        
        # 2. Outcome Selection logic
        outcome = SupervisorOutcome.SILENT
        message_template = ""
        
        if e_type == "WAITING_INPUT":
            summary = event.get("summary") or "needs input"
            message_template = "The {role} is waiting for your input: {summary}"
            outcome = SupervisorOutcome.INPUT if is_focused else SupervisorOutcome.CHAT
            
        elif e_type == "FAILED":
            summary = event.get("failure_summary") or event.get("summary") or "failed"
            message_template = "The {role} failed: {summary}"
            outcome = SupervisorOutcome.CHAT if (score > 10 or not is_stale) else SupervisorOutcome.PANEL
            
        elif e_type == "RECOVERY_NEEDED":
            summary = event.get("failure_summary") or event.get("summary") or "needs recovery"
            message_template = "The {role} encountered a recoverable issue: {summary}. Analyzing next steps."
            outcome = SupervisorOutcome.PANEL if not is_focused else SupervisorOutcome.CHAT
            
        elif e_type == "STALLED":
            summary = event.get("summary") or "no progress reported"
            message_template = "The {role} appears to be STALLED: {summary}"
            outcome = SupervisorOutcome.CHAT if is_focused else SupervisorOutcome.PANEL
            
        elif e_type == "DEGRADED_EXECUTION":
            summary = event.get("summary") or "running with reduced capability"
            message_template = "The {role} is in DEGRADED mode: {summary}"
            outcome = SupervisorOutcome.PANEL if not is_focused else SupervisorOutcome.SILENT
            
        elif e_type == "ATTENTION_REQUIRED":
            summary = event.get("summary") or "blocked"
            message_template = "The {role} requires attention: {summary}"
            outcome = SupervisorOutcome.INPUT if is_focused else SupervisorOutcome.CHAT
            
        elif e_type == "COMPLETED":
            summary = event.get("summary") or "has finished its task"
            message_template = "The {role} has completed its task: {summary}"
            outcome = SupervisorOutcome.CHAT if (score > 30 or (attention in {"medium", "high"} and not is_stale)) else SupervisorOutcome.PANEL
            
        elif e_type == "PROGRESS":
            summary = event.get("summary") or "making progress"
            message_template = "Status: {role} is {summary}."
            outcome = SupervisorOutcome.PANEL if (score > 20 or attention == "high") else SupervisorOutcome.SILENT

        return {
            "outcome": outcome,
            "score": score,
            "message_template": message_template,
            "is_stale": is_stale,
            "turn_distance": turn_dist,
            "attention": attention,
            "event_type": e_type
        }

    @classmethod
    def evaluate_focus_shift(
        cls, 
        event_type: str, 
        attention: str, 
        current_focus_id: Optional[str], 
        task_id: str
    ) -> bool:
        """
        Heuristic for whether focus should shift to the task that emitted this event.
        """
        if current_focus_id == task_id:
            return False
            
        # Focus shifts on WAITING_INPUT or non-low attention
        if event_type == "WAITING_INPUT" or attention in {"medium", "high"}:
            return True
            
        return False

    @classmethod
    def should_trigger_proactive_check(
        cls, 
        last_interaction_age: float, 
        active_sessions_count: int,
        has_system_triggers: bool
    ) -> bool:
        """
        Deterministic trigger for proactive pulse.
        """
        # Triggers if no activity for 60s and system findings exist
        if active_sessions_count == 0 and has_system_triggers:
            return True
        return False

    @classmethod
    def evaluate_guardrails(
        cls,
        repeat_count: int,
        failure_count: int,
        loop_threshold: Optional[int] = None,
        failure_threshold: Optional[int] = None
    ) -> Optional[str]:
        """
        Evaluates if guardrails should be triggered based on repeated actions/failures.
        Returns the guardrail 'code' (e.g. 'loop_guardrail', 'failure_guardrail') or None.
        """
        l_thresh = loop_threshold or cls.LOOP_DETECTION_THRESHOLD
        f_thresh = failure_threshold or cls.FAILURE_LOOP_THRESHOLD
        
        if repeat_count >= l_thresh:
            return "loop_guardrail"
        if failure_count >= f_thresh:
            return "failure_guardrail"
        return None
    @classmethod
    def should_suppress_output(
        cls,
        active_alerts: List[Dict[str, Any]],
        is_system_turn: bool = False
    ) -> bool:
        """
        Policy to decide if Atlas should remain silent.
        If it's a system turn (proactive) and no CHAT/INPUT alerts are present, suppress.
        """
        if is_system_turn:
            # Check if any alert is user-facing
            has_user_facing = any(d["outcome"] in {SupervisorOutcome.CHAT, SupervisorOutcome.INPUT} for d in active_alerts)
            return not has_user_facing
        return False
