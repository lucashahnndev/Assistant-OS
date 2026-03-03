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
from config.manager import ConfigManager

logger = logging.getLogger("Scheduler")
SYSTEM_WORKER_ANCHOR_SESSION_ID = "__system_worker_anchor__"

class WorkStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    PAUSED = "paused"
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
    owner_session_id: Optional[str] = None
    favorite_session_id: Optional[str] = None
    owner_sender_id: Optional[str] = None
    favorite_sender_id: Optional[str] = None
    scope: str = "global"
    work_dir: Optional[str] = None
    context_file: Optional[str] = None
    status_file: Optional[str] = None
    events_file: Optional[str] = None
    controls_media: bool = False
    
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
            "key": self.key,
            "owner_session_id": self.owner_session_id,
            "favorite_session_id": self.favorite_session_id,
            "owner_sender_id": self.owner_sender_id,
            "favorite_sender_id": self.favorite_sender_id,
            "scope": self.scope,
            "work_dir": self.work_dir,
            "context_file": self.context_file,
            "status_file": self.status_file,
            "events_file": self.events_file,
            "controls_media": self.controls_media,
        }

@dataclass
class TaskDefinition:
    task_id: str
    name: str
    context: str
    owner_session_id: Optional[str] = None
    owner_sender_id: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "name": self.name,
            "context": self.context,
            "owner_session_id": self.owner_session_id,
            "owner_sender_id": self.owner_sender_id,
            "notes": self.notes,
            "created_at": self.created_at.isoformat()
        }

    @staticmethod
    def from_dict(data):
        return TaskDefinition(
            task_id=data["task_id"],
            name=data["name"],
            context=data["context"],
            owner_session_id=data.get("owner_session_id"),
            owner_sender_id=data.get("owner_sender_id"),
            notes=data.get("notes", []),
            created_at=datetime.datetime.fromisoformat(data["created_at"])
        )

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
        self._work_commands: Dict[str, List[Dict[str, Any]]] = {}
        self.running = False
        self.thread = None
        
        base_data_dir = ConfigManager.get_data_dir()
        self.data_dir = os.path.abspath(base_data_dir)
        self.jobs_file = os.path.join(self.data_dir, "scheduler_data.json")
        self.logs_dir = os.path.join(self.data_dir, "execution_logs")
        self.sessions_dir = os.path.join(self.data_dir, "sessions")
        self.global_works_dir = os.path.join(self.data_dir, "works")
        
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.sessions_dir, exist_ok=True)
        os.makedirs(self.global_works_dir, exist_ok=True)
        
        self.load_data()

    @staticmethod
    def _is_active_work_status(status: WorkStatus) -> bool:
        return status in {WorkStatus.QUEUED, WorkStatus.RUNNING, WorkStatus.WAITING_USER, WorkStatus.PAUSED}

    @staticmethod
    def _is_terminal_work_status(status: WorkStatus) -> bool:
        return status in {WorkStatus.SUCCEEDED, WorkStatus.FAILED, WorkStatus.CANCELLED}

    @staticmethod
    def _can_transition_work_status(current: WorkStatus, target: WorkStatus) -> bool:
        if current == target:
            return True
        allowed = {
            WorkStatus.QUEUED: {WorkStatus.RUNNING, WorkStatus.CANCELLED, WorkStatus.FAILED},
            WorkStatus.RUNNING: {WorkStatus.WAITING_USER, WorkStatus.PAUSED, WorkStatus.SUCCEEDED, WorkStatus.FAILED, WorkStatus.CANCELLED},
            WorkStatus.WAITING_USER: {WorkStatus.RUNNING, WorkStatus.CANCELLED, WorkStatus.FAILED},
            WorkStatus.PAUSED: {WorkStatus.RUNNING, WorkStatus.CANCELLED, WorkStatus.FAILED},
            WorkStatus.SUCCEEDED: set(),
            WorkStatus.FAILED: set(),
            WorkStatus.CANCELLED: set(),
        }
        return target in allowed.get(current, set())

    # --- Work Management (Ad-Hoc / Chat) ---
    def _resolve_work_paths(self, work_id: str, session_id: str, owner_session_id: str, scope: str) -> Dict[str, str]:
        normalized_scope = "global" if str(scope).lower() == "global" else "session"
        if normalized_scope == "global":
            work_dir = os.path.join(self.global_works_dir, work_id)
        else:
            owner = owner_session_id or session_id or "default"
            work_dir = os.path.join(self.sessions_dir, owner, "works", work_id)
        os.makedirs(work_dir, exist_ok=True)
        return {
            "work_dir": work_dir,
            "context_file": os.path.join(work_dir, "context.json"),
            "status_file": os.path.join(work_dir, "work.json"),
            "events_file": os.path.join(work_dir, "events.jsonl"),
        }

    @staticmethod
    def _is_media_key(key: Optional[str]) -> bool:
        value = str(key or "").strip().lower()
        if not value:
            return False
        media_prefixes = (
            "browser.control.run",
            "browser.control.step",
            "youtube.search.",
            "deezer.search.",
            "spotify.search.",
        )
        return any(value.startswith(prefix) for prefix in media_prefixes)

    @staticmethod
    def _safe_write_json(path: str, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    @staticmethod
    def _deep_merge_dict(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base or {})
        for key, value in (patch or {}).items():
            current = merged.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                merged[key] = Scheduler._deep_merge_dict(current, value)
            else:
                merged[key] = value
        return merged

    def _append_event(self, work: Work, event_type: str, payload: Dict[str, Any]) -> None:
        if not work.events_file:
            return
        try:
            record = {
                "ts": datetime.datetime.now().isoformat(),
                "event": event_type,
                "work_id": work.work_id,
                "session_id": work.session_id,
                "owner_session_id": work.owner_session_id,
                "favorite_session_id": work.favorite_session_id,
                "owner_sender_id": work.owner_sender_id,
                "favorite_sender_id": work.favorite_sender_id,
                "payload": payload or {},
            }
            with open(work.events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to append work event {work.work_id}: {e}")

    def _persist_work_status(self, work: Work) -> None:
        if not work.status_file:
            return
        try:
            self._safe_write_json(work.status_file, work.to_dict())
        except Exception as e:
            logger.error(f"Failed to persist work status {work.work_id}: {e}")

    def _persist_work_context(self, work: Work, context_payload: Dict[str, Any]) -> None:
        if not work.context_file:
            return
        try:
            payload = {
                "work_id": work.work_id,
                "session_id": work.session_id,
                "owner_session_id": work.owner_session_id,
                "favorite_session_id": work.favorite_session_id,
                "owner_sender_id": work.owner_sender_id,
                "favorite_sender_id": work.favorite_sender_id,
                "scope": work.scope,
                "updated_at": datetime.datetime.now().isoformat(),
            }
            payload.update(context_payload or {})
            self._safe_write_json(work.context_file, payload)
        except Exception as e:
            logger.error(f"Failed to persist work context {work.work_id}: {e}")

    def update_work_context(self, work_id: str, context_patch: Dict[str, Any]):
        with self._lock:
            work = self.registry.get(work_id)
            if not work:
                return
            current = {}
            if work.context_file and os.path.exists(work.context_file):
                try:
                    with open(work.context_file, "r", encoding="utf-8") as f:
                        current = json.load(f)
                except Exception:
                    current = {}
            current = self._deep_merge_dict(current, context_patch or {})
            self._persist_work_context(work, current)
            self._append_event(work, "context_update", context_patch or {})

    def push_work_command(
        self,
        work_id: str,
        command: str,
        payload: Optional[Dict[str, Any]] = None,
        source_session_id: Optional[str] = None,
    ) -> bool:
        with self._lock:
            work = self.registry.get(work_id)
            if not work:
                return False
            entry = {
                "ts": datetime.datetime.now().isoformat(),
                "command": str(command or "").strip().lower(),
                "payload": payload or {},
                "source_session_id": source_session_id,
            }
            bucket = self._work_commands.setdefault(work_id, [])
            bucket.append(entry)
            self._append_event(work, "work_command", entry)
            if self.event_bus:
                self.event_bus.put(
                    {
                        "type": "work_command",
                        "work_id": work_id,
                        "session_id": work.session_id,
                        "owner_session_id": work.owner_session_id,
                        "favorite_session_id": work.favorite_session_id,
                        "owner_sender_id": work.owner_sender_id,
                        "favorite_sender_id": work.favorite_sender_id,
                        "command": entry["command"],
                    }
                )
            return True

    def pop_work_commands(self, work_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            commands = self._work_commands.get(work_id, [])
            if commands:
                self._work_commands[work_id] = []
            return list(commands)

    def get_work_context(self, work_id: str) -> Dict[str, Any]:
        with self._lock:
            work = self.registry.get(work_id)
            if not work or not work.context_file or not os.path.exists(work.context_file):
                return {}
            try:
                with open(work.context_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}

    def create_work(
        self,
        session_id: str,
        input_text: str,
        label: str = None,
        key: str = None,
        owner_session_id: str = None,
        favorite_session_id: str = None,
        owner_sender_id: str = None,
        favorite_sender_id: str = None,
        scope: str = "global",
        initial_context: Dict[str, Any] = None,
    ) -> Work:
        work_id = str(uuid.uuid4())[:8]
        is_global_transient_runtime = (
            str(scope).lower() == "global"
            and owner_session_id is None
            and str(session_id or "").startswith("global-task-")
        )
        if is_global_transient_runtime:
            owner = SYSTEM_WORKER_ANCHOR_SESSION_ID
            favorite = favorite_session_id if favorite_session_id is not None else None
        else:
            owner = owner_session_id or session_id
            favorite = favorite_session_id or owner
        paths = self._resolve_work_paths(work_id, session_id, owner, scope)
        controls_media = self._is_media_key(key)
        work = Work(
            work_id=work_id,
            session_id=session_id,
            input_text=input_text,
            label=label,
            key=key,
            owner_session_id=owner,
            favorite_session_id=favorite,
            owner_sender_id=owner_sender_id,
            favorite_sender_id=favorite_sender_id or owner_sender_id,
            scope="global" if str(scope).lower() == "global" else "session",
            work_dir=paths["work_dir"],
            context_file=paths["context_file"],
            status_file=paths["status_file"],
            events_file=paths["events_file"],
            controls_media=controls_media,
        )
        with self._lock:
            self.registry[work_id] = work
            self._persist_work_status(work)
            self._persist_work_context(
                work,
                {
                    "input_text": input_text,
                    "label": label,
                    "key": key,
                    "summary": {
                        "goal": label or key or "Execute task",
                        "action_key": key,
                        "status": "queued",
                        "controls_media": controls_media,
                        "media_control_state": "acquired" if controls_media else "n/a",
                    },
                    "session_snapshot": {
                        "session_id": session_id,
                        "owner_session_id": owner,
                        "favorite_session_id": favorite,
                        "owner_sender_id": owner_sender_id,
                        "favorite_sender_id": favorite_sender_id or owner_sender_id,
                    },
                    "planner": initial_context.get("planner", {}) if isinstance(initial_context, dict) else {},
                    "data": initial_context.get("data", {}) if isinstance(initial_context, dict) else {},
                },
            )
            self._append_event(work, "created", {"label": label, "key": key, "scope": work.scope})
        logger.info(f"Created Work {work_id} [Session: {session_id}]")
        return work

    def get_work(self, work_id: str) -> Optional[Work]:
        with self._lock:
            return self.registry.get(work_id)

    def list_active_works(self):
        with self._lock:
            return [
                w.to_dict() for w in self.registry.values() 
                if self._is_active_work_status(w.status)
            ]

    def get_active_works(
        self,
        session_id: Optional[str] = None,
        owner_session_id: Optional[str] = None,
        key_prefix: Optional[str] = None,
    ) -> List[Work]:
        with self._lock:
            works = [w for w in self.registry.values() if self._is_active_work_status(w.status)]
        if session_id:
            works = [w for w in works if w.session_id == session_id]
        if owner_session_id:
            works = [w for w in works if w.owner_session_id == owner_session_id]
        if key_prefix:
            prefix = str(key_prefix).strip().lower()
            works = [w for w in works if str(w.key or "").lower().startswith(prefix)]
        return works

    def list_works(
        self,
        include_completed: bool = False,
        session_id: Optional[str] = None,
        owner_session_id: Optional[str] = None,
        favorite_session_id: Optional[str] = None,
        limit: int = 200,
        include_context: bool = False,
    ):
        with self._lock:
            items = list(self.registry.values())

        if session_id:
            items = [w for w in items if w.session_id == session_id]
        if owner_session_id:
            items = [w for w in items if w.owner_session_id == owner_session_id]
        if favorite_session_id:
            items = [w for w in items if w.favorite_session_id == favorite_session_id]
        if not include_completed:
            active = {WorkStatus.QUEUED, WorkStatus.RUNNING, WorkStatus.WAITING_USER, WorkStatus.PAUSED}
            items = [w for w in items if w.status in active]

        items.sort(key=lambda w: w.updated_at, reverse=True)
        if limit and limit > 0:
            items = items[:limit]

        output = []
        for work in items:
            row = work.to_dict()
            if include_context and work.context_file and os.path.exists(work.context_file):
                try:
                    with open(work.context_file, "r", encoding="utf-8") as f:
                        row["context"] = json.load(f)
                except Exception:
                    row["context"] = {}
            output.append(row)
        return output

    def get_work_snapshot(self, work_id: str, include_context: bool = True) -> Optional[Dict[str, Any]]:
        with self._lock:
            work = self.registry.get(work_id)
        if not work:
            return None
        payload = work.to_dict()
        if include_context and work.context_file and os.path.exists(work.context_file):
            try:
                with open(work.context_file, "r", encoding="utf-8") as f:
                    payload["context"] = json.load(f)
            except Exception:
                payload["context"] = {}
        return payload
            
    def cancel_session_work(self, session_id: str):
        """Cancel visible loading works for a session to prevent interleaving"""
        with self._lock:
            for work in self.registry.values():
                if work.session_id == session_id and work.status in [WorkStatus.QUEUED, WorkStatus.RUNNING, WorkStatus.WAITING_USER, WorkStatus.PAUSED]:
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

    def force_takeover_cancel(self, work_id: str, reason: str = "forced_takeover"):
        with self._lock:
            work = self.registry.get(work_id)
            if not work:
                return
            work.cancel_requested = True
            self._append_event(work, "forced_takeover", {"reason": reason})
        self.update_work_status(
            work_id,
            WorkStatus.CANCELLED,
            error=f"Forced takeover: {reason}",
        )

    def update_work_status(self, work_id: str, status: WorkStatus, result: str = None, error: str = None):
         with self._lock:
            work = self.registry.get(work_id)
            if work:
                previous = work.status
                if not self._can_transition_work_status(previous, status):
                    # Ignore invalid/late transitions to keep terminal states immutable.
                    logger.warning(
                        "Ignoring invalid work status transition for %s: %s -> %s",
                        work_id,
                        previous.value,
                        status.value,
                    )
                    self._append_event(
                        work,
                        "status_transition_ignored",
                        {"from": previous.value, "to": status.value, "reason": "invalid_transition"},
                    )
                    return
                work.status = status
                work.updated_at = datetime.datetime.now()
                if status == WorkStatus.RUNNING and not work.started_at:
                    work.started_at = datetime.datetime.now()
                if result: work.result = result
                if error: work.error = error
                self._persist_work_status(work)
                if work.controls_media:
                    # Preserve existing planner/data blocks when updating media control status.
                    current_context = {}
                    if work.context_file and os.path.exists(work.context_file):
                        try:
                            with open(work.context_file, "r", encoding="utf-8") as f:
                                current_context = json.load(f)
                        except Exception:
                            current_context = {}
                    merged_context = self._deep_merge_dict(
                        current_context,
                        {
                            "summary": {
                                "controls_media": True,
                                "media_control_state": (
                                    "released" if self._is_terminal_work_status(status) else "acquired"
                                ),
                                "status": status.value,
                            }
                        },
                    )
                    self._persist_work_context(work, merged_context)
                self._append_event(
                    work,
                    "status_change",
                    {
                        "status": status.value,
                        "result": (result[:400] if isinstance(result, str) else None),
                        "error": error,
                    },
                )

                # EMIT EVENT: Notify Kernel of status change
                if self.event_bus:
                    self.event_bus.put({
                        "type": "work_status_change",
                        "work_id": work_id,
                        "session_id": work.session_id,
                        "owner_session_id": work.owner_session_id,
                        "favorite_session_id": work.favorite_session_id,
                        "owner_sender_id": work.owner_sender_id,
                        "favorite_sender_id": work.favorite_sender_id,
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
                work.updated_at = datetime.datetime.now()
                self._persist_work_status(work)
                self._append_event(work, "progress", {"message": message})
                # EMIT EVENT: Notify Kernel of progress
                if self.event_bus:
                    self.event_bus.put({
                        "type": "work_progress",
                        "work_id": work_id,
                        "session_id": work.session_id,
                        "owner_session_id": work.owner_session_id,
                        "favorite_session_id": work.favorite_session_id,
                        "owner_sender_id": work.owner_sender_id,
                        "favorite_sender_id": work.favorite_sender_id,
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

    @staticmethod
    def _parse_dt(value: Any, fallback: Optional[datetime.datetime] = None) -> datetime.datetime:
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.datetime.fromisoformat(value)
            except Exception:
                pass
        return fallback or datetime.datetime.now()

    @staticmethod
    def _parse_work_status(value: Any) -> WorkStatus:
        raw = str(value or "").strip().lower()
        aliases = {
            "completed": WorkStatus.SUCCEEDED,
            "complete": WorkStatus.SUCCEEDED,
            "success": WorkStatus.SUCCEEDED,
            "error": WorkStatus.FAILED,
            "stopped": WorkStatus.CANCELLED,
        }
        if raw in aliases:
            return aliases[raw]
        try:
            return WorkStatus(raw)
        except Exception:
            return WorkStatus.QUEUED

    def _load_works_from_disk(self):
        loaded = 0
        candidates: List[str] = []

        # Global works
        if os.path.isdir(self.global_works_dir):
            for entry in os.listdir(self.global_works_dir):
                candidates.append(os.path.join(self.global_works_dir, entry, "work.json"))

        # Session-scoped works
        if os.path.isdir(self.sessions_dir):
            for owner in os.listdir(self.sessions_dir):
                works_root = os.path.join(self.sessions_dir, owner, "works")
                if not os.path.isdir(works_root):
                    continue
                for entry in os.listdir(works_root):
                    candidates.append(os.path.join(works_root, entry, "work.json"))

        for status_path in candidates:
            if not os.path.exists(status_path):
                continue
            try:
                with open(status_path, "r", encoding="utf-8") as f:
                    row = json.load(f)
                work_id = str(row.get("work_id") or "").strip()
                if not work_id:
                    continue
                if work_id in self.registry:
                    continue

                work_dir = os.path.dirname(status_path)
                context_file = os.path.join(work_dir, "context.json")
                events_file = os.path.join(work_dir, "events.jsonl")

                work = Work(
                    work_id=work_id,
                    session_id=str(row.get("session_id") or "default"),
                    input_text=str(row.get("input_text") or ""),
                    status=self._parse_work_status(row.get("status")),
                    created_at=self._parse_dt(row.get("created_at")),
                    started_at=self._parse_dt(row.get("started_at"), fallback=None) if row.get("started_at") else None,
                    updated_at=self._parse_dt(row.get("updated_at")),
                    result=row.get("result"),
                    error=row.get("error"),
                    progress_updates=list(row.get("progress_updates") or []),
                    cancel_requested=bool(row.get("cancel_requested", False)),
                    label=row.get("label"),
                    key=row.get("key"),
                    owner_session_id=row.get("owner_session_id"),
                    favorite_session_id=row.get("favorite_session_id"),
                    owner_sender_id=row.get("owner_sender_id"),
                    favorite_sender_id=row.get("favorite_sender_id"),
                    scope=str(row.get("scope") or "global"),
                    work_dir=work_dir,
                    context_file=context_file,
                    status_file=status_path,
                    events_file=events_file,
                    controls_media=bool(row.get("controls_media", False)),
                )
                self.registry[work_id] = work
                loaded += 1
            except Exception as e:
                logger.warning(f"Skipping invalid persisted work file {status_path}: {e}")

        if loaded:
            logger.info(f"Loaded {loaded} persisted works from disk.")

    def load_data(self):
        if not os.path.exists(self.jobs_file):
            # Even without scheduler_data.json, persisted works may exist on disk.
            self._load_works_from_disk()
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

                self._load_works_from_disk()

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
    def create_task(
        self,
        name: str,
        context: str,
        owner_session_id: Optional[str] = None,
        owner_sender_id: Optional[str] = None,
    ) -> TaskDefinition:
        task_id = str(uuid.uuid4())[:8]
        task = TaskDefinition(
            task_id=task_id,
            name=name,
            context=context,
            owner_session_id=owner_session_id,
            owner_sender_id=owner_sender_id,
        )
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
            # Global tasks should not force-create a chat session.
            # If owner_session_id is missing, runtime may use a transient worker-only session id.
            "session_id": task.owner_session_id,
            "owner_session_id": task.owner_session_id or SYSTEM_WORKER_ANCHOR_SESSION_ID,
            "owner_sender_id": task.owner_sender_id,
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
    def read_work_events(self, work_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            work = self.registry.get(work_id)
        if not work or not work.events_file or not os.path.exists(work.events_file):
            return []
        try:
            records: List[Dict[str, Any]] = []
            with open(work.events_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        continue
            if limit > 0:
                return records[-limit:]
            return records
        except Exception:
            return []
