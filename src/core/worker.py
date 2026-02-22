import threading
import logging
import queue
import time
import datetime
from typing import Callable, Any, Dict
from core.scheduler import WorkStatus, Scheduler

logger = logging.getLogger("Worker")

class Worker(threading.Thread):
    """
    Executes an Orchestrator task in a separate thread.
    Communicates progress and results back to the Scheduler/EventBus.
    """
    def __init__(self, work_id: str, scheduler: Scheduler, task_fn: Callable, *args, execution_id: str = None, **kwargs):
        super().__init__(daemon=True)
        self.work_id = work_id
        self.execution_id = execution_id
        self.scheduler = scheduler
        self.task_fn = task_fn
        self.args = args
        self.kwargs = kwargs
        self.name = f"Worker-{work_id}"

    def run(self):
        logger.info(f"Worker {self.work_id} (Exec: {self.execution_id}) started execution.")
        
        if self.execution_id:
            self.scheduler.update_execution_status(self.execution_id, "running")
        else:
            self.scheduler.update_work_status(self.work_id, WorkStatus.RUNNING)
        
        try:
            # We inject a progress callback into the task_fn if it supports it
            # The orchestrator.process supports 'on_partial_response'
            def progress_callback(msg):
                if self.execution_id:
                    self.scheduler.add_execution_log(self.execution_id, msg)
                else:
                    self.scheduler.add_progress(self.work_id, msg)
            
            def is_cancelled():
                if self.execution_id:
                     # TODO: Implement cancellation for executions
                     return False
                work = self.scheduler.get_work(self.work_id)
                return work.cancel_requested if work else False
            
            # Add or override callbacks
            self.kwargs['on_partial_response'] = progress_callback
            self.kwargs['cancel_check'] = is_cancelled
            
            # Execute the actual processing
            result = self.task_fn(*self.args, **self.kwargs)
            
            # Check for cancellation right after execution (cooperative)
            if self.execution_id:
                 self.scheduler.update_execution_status(self.execution_id, "succeeded", result=result)
                 logger.info(f"Worker {self.work_id} Finished (Success).")
            else:
                work = self.scheduler.get_work(self.work_id)
                if work and work.cancel_requested:
                    self.scheduler.update_work_status(self.work_id, WorkStatus.CANCELLED)
                    logger.info(f"Worker {self.work_id} Finished (Cancelled).")
                else:
                    self.scheduler.update_work_status(self.work_id, WorkStatus.SUCCEEDED, result=result)
                    logger.info(f"Worker {self.work_id} Finished (Success).")
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Worker {self.work_id} Failed: {error_msg}", exc_info=True)
            
            # Injection: Update session state with the error so the agent knows in the next turn
            session_id = self.kwargs.get('session_id')
            if session_id:
                try:
                    from core.orchestrator import AgentOrchestrator
                    orch = AgentOrchestrator()
                    session = orch.sessions.get(session_id)
                    if session:
                        session.state_summary['last_error'] = error_msg
                        session.state_summary['status'] = "error_detected"
                        session.state_summary['retry_count'] = session.state_summary.get('retry_count', 0) + 1
                        # Add a system message so it's in the history
                        session.add_message("system", f"ERRO CRÍTICO NO WORKER: {error_msg}")
                        orch._save_session(session)
                except Exception as ex:
                    logger.error(f"Failed to inject worker error into session: {ex}")

            if self.execution_id:
                self.scheduler.update_execution_status(self.execution_id, "failed", error=error_msg)
            else:
                self.scheduler.update_work_status(self.work_id, WorkStatus.FAILED, error=error_msg)

class WorkerManager:
    """
    Responsible for spawning and tracking Worker threads.
    """
    def __init__(self, scheduler: Scheduler):
        self.scheduler = scheduler
        self.active_workers: Dict[str, Worker] = {}
        self._lock = threading.Lock()

    def spawn_worker(self, work_id: str, task_fn: Callable, *args, **kwargs):
        worker = Worker(work_id, self.scheduler, task_fn, *args, **kwargs)
        with self._lock:
            self.active_workers[work_id] = worker
        worker.start()
        return worker

    def watchdog_check(self):
        """
        Detects dead or hung workers and cleans up the active list.
        """
        with self._lock:
            dead_works = []
            for work_id, worker in self.active_workers.items():
                if not worker.is_alive():
                    dead_works.append(work_id)
                else:
                    # Check for hung worker (e.g., status RUNNING but updated_at is > 5 min ago)
                    work = self.scheduler.get_work(work_id)
                    if work and work.status == WorkStatus.RUNNING:
                        age = (datetime.datetime.now() - work.updated_at).total_seconds()
                        if age > 300: # 5 minutes
                            logger.warning(f"Worker {work_id} appears to be hung (Age: {age}s).")
                            # We can't easily kill a python thread from outside, 
                            # but we can mark it as failed in the registry.
                            self.scheduler.update_work_status(work_id, WorkStatus.FAILED, error="Timeout: Tarefa travada.")
                            dead_works.append(work_id)

            for work_id in dead_works:
                del self.active_workers[work_id]
