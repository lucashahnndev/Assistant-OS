import uuid
import datetime
import threading
import queue
import logging
import json
import os
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union, Any, Callable
from croniter import croniter
import holidays

logger = logging.getLogger("Scheduler")

class WorkStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"

@dataclass
class Work:
    work_id: str
    session_id: str
    input_text: str
    status: WorkStatus = WorkStatus.QUEUED
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    started_at: Optional[datetime.datetime] = None
    updated_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    result: Optional[str] = None
    error: Optional[str] = None
    progress_updates: list = field(default_factory=list)
    worker_handle: Optional[threading.Thread] = None
    cancel_requested: bool = False
    label: Optional[str] = None
    key: Optional[str] = None
    
    def to_dict(self):
        return {
            "work_id": self.work_id,
            "session_id": self.session_id,
            "input_text": self.input_text,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat(),
            "result": self.result,
            "error": self.error,
            "progress_count": len(self.progress_updates),
            "cancel_requested": self.cancel_requested,
            "label": self.label,
            "key": self.key
        }

@dataclass
class TaskDefinition:
    task_id: str
    name: str
    context: str
    notes: list[str] = field(default_factory=list)
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "name": self.name,
            "context": self.context,
            "notes": self.notes,
            "created_at": self.created_at.isoformat()
        }

    @staticmethod
    def from_dict(data):
        return TaskDefinition(
            task_id=data["task_id"],
            name=data["name"],
            context=data["context"],
            notes=data.get("notes", []),
            created_at=datetime.datetime.fromisoformat(data["created_at"])
        )

class WorkStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"

@dataclass
class Work:
    work_id: str
    session_id: str
    input_text: str
    status: WorkStatus = WorkStatus.QUEUED
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    started_at: Optional[datetime.datetime] = None
    updated_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    result: Optional[str] = None
    error: Optional[str] = None
    progress_updates: list = field(default_factory=list)
    worker_handle: Optional[threading.Thread] = None
    cancel_requested: bool = False
    label: Optional[str] = None
    key: Optional[str] = None
    
    def to_dict(self):
        return {
            "work_id": self.work_id,
            "session_id": self.session_id,
            "input_text": self.input_text,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat(),
            "result": self.result,
            "error": self.error,
            "progress_count": len(self.progress_updates),
            "cancel_requested": self.cancel_requested,
            "label": self.label,
            "key": self.key
        }

@dataclass
class ScheduleTrigger:
    trigger_id: str
    task_id: str
    schedule_type: str  # interval, cron, date
    schedule_value: Union[int, str]
    holiday_rules: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[datetime.datetime] = None
    next_run: Optional[datetime.datetime] = None
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)

    def to_dict(self):
        return {
            "trigger_id": self.trigger_id,
            "task_id": self.task_id,
            "schedule_type": self.schedule_type,
            "schedule_value": self.schedule_value,
            "holiday_rules": self.holiday_rules,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "created_at": self.created_at.isoformat()
        }

    @staticmethod
    def from_dict(data):
        trigger = ScheduleTrigger(
            trigger_id=data["trigger_id"],
            task_id=data["task_id"],
            schedule_type=data["schedule_type"],
            schedule_value=data["schedule_value"],
            holiday_rules=data.get("holiday_rules", {}),
            enabled=data.get("enabled", True)
        )
        if data.get("last_run"):
            trigger.last_run = datetime.datetime.fromisoformat(data["last_run"])
        if data.get("next_run"):
            trigger.next_run = datetime.datetime.fromisoformat(data["next_run"])
        if data.get("created_at"):
            trigger.created_at = datetime.datetime.fromisoformat(data["created_at"])
        return trigger

@dataclass
class TaskExecution:
    execution_id: str
    task_id: str
    trigger_id: Optional[str]
    status: str # running, success, failed
    start_time: datetime.datetime = field(default_factory=datetime.datetime.now)
    end_time: Optional[datetime.datetime] = None
    log_file: Optional[str] = None # Path to detailed log
    cancel_requested: bool = False

    def to_dict(self):
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "trigger_id": self.trigger_id,
            "status": self.status,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "log_file": self.log_file,
            "cancel_requested": self.cancel_requested
        }
    
    @staticmethod
    def from_dict(data):
        exec = TaskExecution(
            execution_id=data["execution_id"],
            task_id=data["task_id"],
            trigger_id=data.get("trigger_id"),
            status=data["status"],
            start_time=datetime.datetime.fromisoformat(data["start_time"]),
            log_file=data.get("log_file")
        )
        if data.get("end_time"):
            exec.end_time = datetime.datetime.fromisoformat(data["end_time"])
        return exec

class Scheduler:
    """
    Registry and Dispatcher for Jobs/Works.
    Manages the lifecycle of asynchronous tasks.
    """
    def __init__(self, event_bus: queue.Queue, persistence_file="scheduler_jobs.json"):
        self.registry: Dict[str, Work] = {}
        self.tasks: Dict[str, TaskDefinition] = {}
        self.triggers: Dict[str, ScheduleTrigger] = {}
        self.executions: Dict[str, TaskExecution] = {}
        self.event_bus = event_bus
        self._lock = threading.Lock()
        self.running = False
        self.thread = None
        
        self.data_dir = os.path.join(os.getcwd(), "data")
        self.jobs_file = os.path.join(self.data_dir, "scheduler_data.json")
        self.logs_dir = os.path.join(self.data_dir, "execution_logs")
        
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)
        
        self.load_data()

    # --- Work Management (Ad-Hoc / Chat) ---
    def create_work(self, session_id: str, input_text: str, label: str = None, key: str = None) -> Work:
        work_id = str(uuid.uuid4())[:8]
        work = Work(
            work_id=work_id,
            session_id=session_id,
            input_text=input_text,
            label=label,
            key=key
        )
        with self._lock:
            self.registry[work_id] = work
        logger.info(f"Created Work {work_id} [Session: {session_id}]")
        return work

    def get_work(self, work_id: str) -> Optional[Work]:
        with self._lock:
            return self.registry.get(work_id)

    def list_active_works(self):
        with self._lock:
            return [
                w.to_dict() for w in self.registry.values() 
                if w.status in [WorkStatus.QUEUED, WorkStatus.RUNNING, WorkStatus.WAITING_USER]
            ]
            
    def cancel_session_work(self, session_id: str):
        """Cancel visible loading works for a session to prevent interleaving"""
        with self._lock:
            for work in self.registry.values():
                if work.session_id == session_id and work.status in [WorkStatus.QUEUED, WorkStatus.RUNNING, WorkStatus.WAITING_USER]:
                    work.cancel_requested = True
                    # If it has a worker handle, strictly we should kill it, 
                    # but simple flag check in worker loop is safer for now.
                    logger.info(f"Requested cancellation for Work {work.work_id} due to new input.")

    def request_cancel(self, work_id: str):
        with self._lock:
            work = self.registry.get(work_id)
            if work:
                work.cancel_requested = True
                logger.info(f"User requested cancellation for Work {work_id}")

    def update_work_status(self, work_id: str, status: WorkStatus, result: str = None, error: str = None):
         with self._lock:
            work = self.registry.get(work_id)
            if work:
                work.status = status
                work.updated_at = datetime.datetime.now()
                if status == WorkStatus.RUNNING and not work.started_at:
                    work.started_at = datetime.datetime.now()
                if result: work.result = result
                if error: work.error = error

                # EMIT EVENT: Notify Kernel of status change
                if self.event_bus:
                    self.event_bus.put({
                        "type": "work_status_change",
                        "work_id": work_id,
                        "session_id": work.session_id,
                        "status": status.value
                    })

    def add_progress(self, work_id: str, message: str):
        with self._lock:
            work = self.registry.get(work_id)
            if work:
                work.progress_updates.append({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "message": message
                })
                # EMIT EVENT: Notify Kernel of progress
                if self.event_bus:
                    self.event_bus.put({
                        "type": "work_progress",
                        "work_id": work_id,
                        "session_id": work.session_id,
                        "message": message
                    })

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("Scheduler started.")

    def stop(self):
        self.running = False
        if hasattr(self, 'thread'):
            self.thread.join()
        logger.info("Scheduler stopped.")

    def _run_loop(self):
        while self.running:
            try:
                self.check_pending_triggers()
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
            time.sleep(1)

    def load_data(self):
        if not os.path.exists(self.jobs_file):
            return
        
        try:
            with open(self.jobs_file, "r") as f:
                data = json.load(f)
                
                # Check format version (list=old, dict=new)
                if isinstance(data, list):
                    logger.warning("Old scheduler format detected. Starting fresh (migration needed).")
                    return

                if "tasks" in data:
                    for t in data["tasks"]:
                        obj = TaskDefinition.from_dict(t)
                        self.tasks[obj.task_id] = obj
                
                if "triggers" in data:
                    for t in data["triggers"]:
                        obj = ScheduleTrigger.from_dict(t)
                        self.triggers[obj.trigger_id] = obj

                if "executions" in data:
                    for t in data["executions"]:
                        obj = TaskExecution.from_dict(t)
                        self.executions[obj.execution_id] = obj

        except Exception as e:
            logger.error(f"Failed to load scheduler data: {e}")

    def save_data(self):
        try:
            data = {
                "tasks": [t.to_dict() for t in self.tasks.values()],
                "triggers": [t.to_dict() for t in self.triggers.values()],
                "executions": [t.to_dict() for t in self.executions.values()]
            }
            with open(self.jobs_file, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save scheduler data: {e}")

    # --- Task Management ---
    def create_task(self, name: str, context: str) -> TaskDefinition:
        task_id = str(uuid.uuid4())[:8]
        task = TaskDefinition(task_id=task_id, name=name, context=context)
        with self._lock:
            self.tasks[task_id] = task
        self.save_data()
        return task

    def update_task_notes(self, task_id: str, notes: List[str]):
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].notes = notes
        self.save_data()

    def add_task_note(self, task_id: str, note: str):
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].notes.append(note)
        self.save_data()

    def delete_task(self, task_id: str):
        with self._lock:
            if task_id in self.tasks:
                del self.tasks[task_id]
                # Cascade delete triggers
                to_del = [tid for tid, t in self.triggers.items() if t.task_id == task_id]
                for tid in to_del:
                    del self.triggers[tid]
        self.save_data()

    # --- Trigger Management ---
    def add_trigger(self, task_id: str, schedule_type: str, schedule_value: Union[str, int], holiday_rules: dict = None) -> ScheduleTrigger:
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        trigger_id = str(uuid.uuid4())[:8]
        trigger = ScheduleTrigger(
            trigger_id=trigger_id,
            task_id=task_id,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            holiday_rules=holiday_rules or {}
        )
        
        now = datetime.datetime.now()
        if schedule_type == "interval":
            # Start next interval from now
            trigger.next_run = now + datetime.timedelta(seconds=int(schedule_value))
        elif schedule_type == "cron":
            if croniter.is_valid(schedule_value):
                iter = croniter(schedule_value, now)
                trigger.next_run = iter.get_next(datetime.datetime)
        elif schedule_type == "date":
            if isinstance(schedule_value, str):
                trigger.next_run = datetime.datetime.fromisoformat(schedule_value.replace("Z", "+00:00"))

        with self._lock:
            self.triggers[trigger_id] = trigger
        self.save_data()
        return trigger

    def delete_trigger(self, trigger_id: str):
        with self._lock:
            if trigger_id in self.triggers:
                del self.triggers[trigger_id]
        self.save_data()

    def toggle_trigger(self, trigger_id: str, enabled: bool):
        with self._lock:
            if trigger_id in self.triggers:
                self.triggers[trigger_id].enabled = enabled
        self.save_data()

    # --- Execution Management ---
    def record_execution(self, task_id: str, trigger_id: Optional[str]) -> TaskExecution:
        execution_id = str(uuid.uuid4())
        
        # Create log file
        log_filename = f"{execution_id}.log"
        log_path = os.path.join(self.logs_dir, log_filename)
        with open(log_path, "w") as f:
            f.write(f"Execution {execution_id} started at {datetime.datetime.now()}\n")

        execution = TaskExecution(
            execution_id=execution_id,
            task_id=task_id,
            trigger_id=trigger_id,
            status="running",
            log_file=log_path
        )
        with self._lock:
            self.executions[execution_id] = execution
        self.save_data()
        return execution

    def update_execution_status(self, execution_id: str, status: str, result: str = None, error: str = None):
        with self._lock:
            if execution_id in self.executions:
                exec_obj = self.executions[execution_id]
                exec_obj.status = status
                if status in ["success", "failed", "cancelled", "succeeded"]:
                     exec_obj.end_time = datetime.datetime.now()
                
                # We don't store result/error in TaskExecution struct yet, 
                # but we should log it
                if result:
                    self.add_execution_log(execution_id, f"\nRESULT: {result}")
                if error:
                    self.add_execution_log(execution_id, f"\nERROR: {error}")

        self.save_data()

    def add_execution_log(self, execution_id: str, message: str):
        # This can be called frequently, so we avoid lock if possible or keep it short
        # But we need to know the path.
        log_file = None
        with self._lock:
            if execution_id in self.executions:
                log_file = self.executions[execution_id].log_file
        
        if log_file:
            try:
                with open(log_file, "a") as f:
                    f.write(f"{message}\n")
            except Exception as e:
                logger.error(f"Failed to write to execution log {execution_id}: {e}")

    def complete_execution(self, execution_id: str, status: str):
        # Deprecated/Alias
        self.update_execution_status(execution_id, status)

    def cancel_execution(self, execution_id: str):
         with self._lock:
            if execution_id in self.executions:
                self.executions[execution_id].cancel_requested = True
                logger.info(f"Requested cancellation for Execution {execution_id}")

    def check_pending_triggers(self):
        now = datetime.datetime.now()
        triggers_to_run = []
        country_holidays = {} 

        with self._lock:
            for trigger in self.triggers.values():
                if not trigger.enabled: continue
                if trigger.task_id not in self.tasks: continue # Orphaned

                # Holiday check
                if trigger.holiday_rules:
                    country = trigger.holiday_rules.get("country", "BR")
                    if country not in country_holidays:
                        country_holidays[country] = holidays.country_holidays(country)
                    
                    is_holiday = now.date() in country_holidays[country]
                    exclude = trigger.holiday_rules.get("exclude", False)
                    only = trigger.holiday_rules.get("only", False)

                    if is_holiday and exclude: continue
                    if not is_holiday and only: continue

                # Initial seed if null
                if not trigger.next_run:
                     if trigger.schedule_type == "interval":
                          trigger.next_run = now + datetime.timedelta(seconds=int(trigger.schedule_value))
                     # ... others should be set on creation.
                
                if trigger.next_run and now >= trigger.next_run:
                    triggers_to_run.append(trigger)
                    trigger.last_run = now
                    
                    # Next run calc
                    if trigger.schedule_type == "interval":
                        trigger.next_run = now + datetime.timedelta(seconds=int(trigger.schedule_value))
                    elif trigger.schedule_type == "cron":
                        iter = croniter(trigger.schedule_value, now)
                        trigger.next_run = iter.get_next(datetime.datetime)
                    elif trigger.schedule_type == "date":
                        trigger.next_run = None
                        trigger.enabled = False

            if triggers_to_run:
                self.save_data()

        for trigger in triggers_to_run:
            self.trigger_execution(trigger.task_id, trigger.trigger_id)

    def trigger_execution(self, task_id: str, trigger_id: Optional[str] = None):
        """
        Triggers a task execution (Scheduled or Manual).
        Creates an execution record and sends event.
        """
        task = self.tasks.get(task_id)
        if not task: return

        # Record Execution Start
        execution = self.record_execution(task_id, trigger_id)
        
        logger.info(f"Executing Task: {task.name} (ExecID: {execution.execution_id})")
        
        # Payload for Orchestrator
        # We include execution_id so Orchestrator can log back to us
        input_text = f"Execute task '{task.name}': {task.context}"
        self.event_bus.put({
            "type": "scheduled_job_trigger", # Keeping type for compatibility, or new type?
            "job_id": task_id, # For backward compat in event consumer if needed
            "execution_id": execution.execution_id,
            "task_id": task_id,
            "input_text": input_text,
            "session_id": "system_scheduler" 
        })

    def list_tasks(self):
        with self._lock:
            return [t.to_dict() for t in self.tasks.values()]
    
    def list_triggers(self, task_id: str = None):
        with self._lock:
            if task_id:
                return [t.to_dict() for t in self.triggers.values() if t.task_id == task_id]
            return [t.to_dict() for t in self.triggers.values()]

    def list_executions(self, task_id: str = None):
        with self._lock:
            if task_id:
                return [e.to_dict() for e in self.executions.values() if e.task_id == task_id]
            return [e.to_dict() for e in self.executions.values()]

    def get_task(self, task_id: str):
        with self._lock:
            t = self.tasks.get(task_id)
            return t.to_dict() if t else None

