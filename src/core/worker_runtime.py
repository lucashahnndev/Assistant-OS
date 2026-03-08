import threading
import time
import logging
import datetime
from typing import Optional, Dict, Any, Callable, List
from core.events import WorkerEvent, WorkerEventType, AttentionLevel, TaskOrigin, TaskSpawnReason
from core.session import Session

logger = logging.getLogger("WorkerRuntime")

class WorkerRuntime:
    """
    Manages the lifecycle of an asynchronous agentic task.
    Workers emit consolidated state updates to the Session's EventInbox.
    
    Refinements:
    - SLOW signal monitoring via last_progress_at.
    - Summary truncation to enforce consolidation.
    - Debounced session saving to optimize IO.
    """
    def __init__(
        self,
        session_id: str,
        task_id: str,
        run_id: str,
        task_role: str,
        turn_id: int,
        base_turn_id: int,
        orchestrator: Any,
        slow_threshold_seconds: float = 30.0,
        intent_group_id: Optional[str] = None,
        origin_type: TaskOrigin = TaskOrigin.SYSTEM,
        parent_task_id: Optional[str] = None,
        spawn_reason: TaskSpawnReason = TaskSpawnReason.USER_REQUEST
    ):
        self.session_id = session_id
        self.task_id = task_id
        self.run_id = run_id
        self.task_role = task_role
        self.turn_id = turn_id
        self.base_turn_id = base_turn_id
        self.orchestrator = orchestrator
        self.slow_threshold = slow_threshold_seconds
        self.intent_group_id = intent_group_id
        self.origin_type = origin_type
        self.parent_task_id = parent_task_id
        self.spawn_reason = spawn_reason
        
        self.last_progress_at = time.time()
        self.last_phase = "initializing"
        self.last_phase_change_at = time.time()
        self.last_artifact_count = 0
        self.last_artifact_at = time.time()
        self.last_summary = ""
        self.latest_checkpoint: Optional[Dict[str, Any]] = None
        self._thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_requested = False
        
        # IO Optimization: Debouncing
        self._last_save_time = 0
        self._save_debounce_seconds = 2.0

    def spawn(self, func: Callable, *args, **kwargs):
        """Spawns the worker and a SLOW signal monitor in background threads."""
        self._thread = threading.Thread(
            target=self._wrap_execution,
            args=(func, *args),
            kwargs=kwargs,
            daemon=True,
            name=f"worker-{self.task_id}"
        )
        self._thread.start()
        
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name=f"monitor-{self.task_id}"
        )
        self._monitor_thread.start()
        
        logger.info(f"Worker spawned: {self.task_id} (Role: {self.task_role}) for session {self.session_id}")

    def _monitor_loop(self):
        """Checks for SLOW/STALLED signals using multi-signal heartbeat."""
        interval = min(5.0, self.slow_threshold / 2.0)
        while not self._stop_requested and self.is_alive():
            time.sleep(interval)
            
            if self.is_superseded():
                logger.info(f"Worker {self.task_id} superseded. Requesting stop.")
                self._stop_requested = True
                break
            
            now = time.time()
            elapsed_total = now - self.last_progress_at
            elapsed_phase = now - self.last_phase_change_at
            
            # Phase 10: Advanced Heartbeat
            # Distinguishes liveness from advancement.
            now = time.time()
            time_since_advance = now - max(self.last_progress_at, self.last_phase_change_at, self.last_artifact_at)
            
            if self._is_stalled(threshold_s=self.slow_threshold):
                self.report_status(
                    event_type=WorkerEventType.STALLED,
                    phase=self.last_phase,
                    progress=0.0,
                    summary=f"Task STALLED. No real advancement for {int(time_since_advance)}s.",
                    attention_level=AttentionLevel.HIGH,
                    metadata={
                        "time_since_last_advance": time_since_advance,
                        "blocked_state": True
                    }
                )
            elif time_since_advance > self.slow_threshold / 2:
                self.report_status(
                    event_type=WorkerEventType.SLOW,
                    phase=self.last_phase,
                    progress=0.0,
                    summary=f"Task SLOW. No advancement for {int(time_since_advance)}s.",
                    attention_level=AttentionLevel.MEDIUM,
                    metadata={"time_since_last_advance": time_since_advance}
                )

    def _wrap_execution(self, func: Callable, *args, **kwargs):
        """Internal wrapper to manage the worker lifecycle events."""
        from core.errors import AgentError, ErrorCode, ErrorCategory
        try:
            self.report_status(
                event_type=WorkerEventType.STARTED,
                phase="initializing",
                progress=0.0,
                summary=f"Starting task: {self.task_role}"
            )
            
            # Execute the actual task logic
            result = func(self, *args, **kwargs)
            
            self.report_status(
                event_type=WorkerEventType.COMPLETED,
                phase="completed",
                progress=1.0,
                summary=f"Task completed successfully: {self.task_role}",
                artifacts=[{"result": result}] if result else []
            )
        except AgentError as e:
            logger.warning(f"Worker {self.task_id} execution error (category: {e.category}): {e.message}")
            
            # Decide if we move to RECOVERY_NEEDED or FAILED
            # Runtime emits the signal, Supervisor decides outcome
            event_type = WorkerEventType.RECOVERY_NEEDED if e.category in [ErrorCategory.TRANSIENT, ErrorCategory.DEPENDENCY] else WorkerEventType.FAILED
            
            self.report_status(
                event_type=event_type,
                phase="recovery_pending" if event_type == WorkerEventType.RECOVERY_NEEDED else "failed",
                progress=0.0,
                summary=f"Task {event_type.value}: {e.message}",
                failure_summary=e.message,
                error_code=e.code.value,
                attention_level=AttentionLevel.HIGH
            )
        except Exception as e:
            logger.exception(f"Worker {self.task_id} unexpected failure: {e}")
            self.report_status(
                event_type=WorkerEventType.FAILED,
                phase="failed",
                progress=0.0,
                summary=f"Task failed: {str(e)}",
                failure_summary=str(e),
                error_code=ErrorCode.UNKNOWN_ERROR.value,
                attention_level=AttentionLevel.HIGH
            )
        finally:
            # Phase 10: Structured Completion/Failure Summary
            is_success = self.last_phase == "completed"
            outcome = "success" if is_success else "failure"
            
            final_summary = {
                "outcome": outcome,
                "final_summary": f"Task {outcome}: {self.last_summary}",
                "artifacts": self.last_artifact_count,
                "pending_issues": ["Unexpected termination"] if not is_success else [],
                "suggested_next_step": "Review artifacts or continue session"
            }
            
            # Final event
            try:
                self.report_status(
                    event_type=WorkerEventType.COMPLETED if is_success else WorkerEventType.FAILED,
                    phase=self.last_phase,
                    progress=1.0 if is_success else 0.0,
                    summary=str(final_summary["final_summary"]),
                    completion_summary=final_summary,
                    attention_level=AttentionLevel.LOW if is_success else AttentionLevel.HIGH
                )
            except Exception as final_err:
                logger.error(f"Failed to report final status for {self.task_id}: {final_err}")
                
            if self.last_phase != "recovery_pending":
                self._stop_requested = True

    def report_status(
        self,
        event_type: WorkerEventType,
        phase: str,
        progress: float,
        summary: str,
        error_code: Optional[str] = None,
        failure_summary: Optional[str] = None,
        needs_user_input: bool = False,
        suggested_user_prompt: Optional[str] = None,
        attention_level: AttentionLevel = AttentionLevel.LOW,
        artifacts: Optional[List[Dict[str, Any]]] = None,
        checkpoint: Optional[Dict[str, Any]] = None,
        completion_summary: Optional[Dict[str, Any]] = None,
        priority_level: Optional[str] = None,
        urgency: Optional[float] = None,
        attention_score: Optional[float] = None,
        user_waiting: bool = False,
        depends_on: Optional[List[str]] = None,
        blocks: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Publishes a consolidated WorkerEvent to the session inbox."""
        # Enforce consolidation contract: Truncation
        def truncate(s: Optional[str], limit: int = 500) -> Optional[str]:
            if s and len(s) > limit:
                return s[:limit-3] + "..."
            return s

        safe_summary = truncate(summary)
        safe_failure = truncate(failure_summary)

        event = WorkerEvent(
            task_id=self.task_id,
            run_id=self.run_id,
            task_role=self.task_role,
            intent_group_id=self.intent_group_id,
            origin_type=self.origin_type,
            parent_task_id=self.parent_task_id,
            spawn_reason=self.spawn_reason,
            turn_id=self.turn_id,
            base_turn_id=self.base_turn_id,
            event_type=event_type,
            phase=phase,
            progress=progress,
            summary=safe_summary or "No summary",
            error_code=error_code,
            failure_summary=safe_failure,
            needs_user_input=needs_user_input,
            suggested_user_prompt=suggested_user_prompt,
            attention_level=attention_level,
            artifacts=artifacts or [],
            checkpoint=checkpoint,
            completion_summary=completion_summary,
            priority_level=priority_level,
            urgency=urgency,
            attention_score=attention_score,
            user_waiting=user_waiting,
            depends_on=depends_on or [],
            blocks=blocks or []
        )
        
        # Merge extra metadata if provided
        if metadata:
            event_dict = event.to_dict()
            event_dict.update(metadata)
            # Re-wrap if needed or send as dict? session.publish_event takes dict.
            msg_dict = event_dict
        else:
            msg_dict = event.to_dict()
        
        # Update monitoring state
        if event_type != WorkerEventType.SLOW:
            now = time.time()
            self.last_progress_at = now
            if phase != self.last_phase:
                self.last_phase = phase
                self.last_phase_change_at = now
            
            curr_art_count = len(artifacts) if artifacts else 0
            if curr_art_count > self.last_artifact_count:
                self.last_artifact_count = curr_art_count
                self.last_artifact_at = now
            self.last_summary = safe_summary or "No summary"

        session = self.orchestrator.get_session_robust(self.session_id)
        if session:
            # Minimize lock scope: session.publish_event should be thread-safe internally
            # (In current session.py it is just list operations, but we should be careful)
            session.publish_event(msg_dict)
            
            # IO Optimization: Debounced save
            now = time.time()
            if now - self._last_save_time > self._save_debounce_seconds or event_type in [WorkerEventType.COMPLETED, WorkerEventType.FAILED]:
                self.orchestrator._save_session(session)
                self._last_save_time = now
        
        return event

    def report_memory(
        self,
        memory_type: str,
        scope: str,
        content: str,
        confidence: float,
        metadata: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None
    ):
        """Proposes a memory candidate to the Supervisor."""
        from core.events import MemoryEntry
        
        candidate = MemoryEntry(
            memory_type=memory_type,
            scope=scope,
            source_type="worker",
            source_id=self.task_id,
            content=content,
            confidence=confidence,
            status="candidate",
            metadata=metadata or {},
            ttl=ttl
        )
        
        # Publish as a special event type
        event_dict = candidate.to_dict()
        event_dict["event_type"] = "MEMORY_CANDIDATE"
        event_dict["task_id"] = self.task_id
        event_dict["task_role"] = self.task_role
        
        session = self.orchestrator.get_session_robust(self.session_id)
        if session:
            session.publish_event(event_dict)

    def stop(self):
        """Requests the worker to stop gracefully."""
        self._stop_requested = True

    def is_alive(self) -> bool:
        return self._thread.is_alive() if self._thread else False

    def is_superseded(self) -> bool:
        """Checks if the task has been marked as superseded in the session registry."""
        session = self.orchestrator.get_session_robust(self.session_id)
        if session:
            task = session.task_registry.get(self.task_id)
            if task and task.get("is_superseded"):
                return True
        return False

    def _is_stalled(self, threshold_s: float) -> bool:
        """
        Sophisticated stall detection (Phase 8.1).
        Distinguishes quiet-but-valid execution from real stalls.
        """
        now = time.time()
        
        # 1. Any progress recently?
        if now - self.last_progress_at < threshold_s:
            return False
            
        # 2. Recent phase change?
        if now - self.last_phase_change_at < threshold_s:
            return False
            
        # 3. Recent artifact produced?
        if now - self.last_artifact_at < threshold_s:
            return False
            
        # 4. Heartbeat alive? (Implied if this is running, but good to check context)
        return True

    def create_checkpoint(
        self,
        summary: str,
        phase: Optional[str] = None,
        progress: Optional[float] = None,
        resumability: str = "resumable_safe",
        completed_substeps: Optional[List[str]] = None,
        side_effect_boundary: bool = False
    ):
        """Creates a structured operational checkpoint."""
        import uuid
        import datetime
        
        checkpoint_id = str(uuid.uuid4())
        checkpoint_data = {
            "task_id": self.task_id,
            "checkpoint_id": checkpoint_id,
            "phase": phase or self.last_phase,
            "progress": progress if progress is not None else 0.5,
            "summary": summary,
            "artifacts_produced": self.last_artifact_count,
            "completed_substeps": completed_substeps or [],
            "resumability": resumability,
            "side_effect_boundary": side_effect_boundary,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        
        self.latest_checkpoint = checkpoint_data
        
        self.report_status(
            event_type=WorkerEventType.CHECKPOINT,
            phase=checkpoint_data["phase"],
            progress=checkpoint_data["progress"],
            summary=f"Checkpoint: {summary}",
            checkpoint=checkpoint_data,
            attention_level=AttentionLevel.LOW
        )
        return checkpoint_id
