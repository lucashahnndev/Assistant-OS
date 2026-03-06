import threading
import time
import logging
import datetime
from typing import Optional, Dict, Any, Callable, List
from core.events import WorkerEvent, WorkerEventType, AttentionLevel
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
        intent_group_id: Optional[str] = None
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
        
        self.last_progress_at = time.time()
        self.last_phase = "initializing"
        self.last_summary = ""
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
        """Checks for SLOW signals if progress hasn't been reported for a while."""
        # Use a dynamic sleep interval based on threshold, but cap it
        interval = min(5.0, self.slow_threshold / 2.0)
        while not self._stop_requested and self.is_alive():
            time.sleep(interval)
            
            # Check for superseding
            if self.is_superseded():
                logger.info(f"Worker {self.task_id} superseded. Requesting stop.")
                self._stop_requested = True
                break
            if time.time() - self.last_progress_at > self.slow_threshold:
                self.report_status(
                    event_type=WorkerEventType.SLOW,
                    phase=self.last_phase,
                    progress=0.0, # Slow signal doesn't imply progress
                    summary=f"Stalled in phase: {self.last_phase}. Last status: {self.last_summary}",
                    attention_level=AttentionLevel.MEDIUM
                )
                # Reset timer so we don't spam SLOW events
                self.last_progress_at = time.time()

    def _wrap_execution(self, func: Callable, *args, **kwargs):
        """Internal wrapper to manage the worker lifecycle events."""
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
        except Exception as e:
            logger.exception(f"Worker {self.task_id} failed: {e}")
            self.report_status(
                event_type=WorkerEventType.FAILED,
                phase="failed",
                progress=0.0,
                summary=f"Task failed: {str(e)}",
                failure_summary=str(e),
                error_code="WORKER_ERROR",
                attention_level=AttentionLevel.HIGH
            )
        finally:
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
        artifacts: Optional[List[Dict[str, Any]]] = None
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
            artifacts=artifacts or []
        )
        
        # Update monitoring state
        if event_type != WorkerEventType.SLOW:
            self.last_progress_at = time.time()
            self.last_phase = phase
            self.last_summary = safe_summary or "No summary"

        session = self.orchestrator.get_session_robust(self.session_id)
        if session:
            # Minimize lock scope: session.publish_event should be thread-safe internally
            # (In current session.py it is just list operations, but we should be careful)
            session.publish_event(event.to_dict())
            
            # IO Optimization: Debounced save
            now = time.time()
            if now - self._last_save_time > self._save_debounce_seconds or event_type in [WorkerEventType.COMPLETED, WorkerEventType.FAILED]:
                self.orchestrator._save_session(session)
                self._last_save_time = now

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
