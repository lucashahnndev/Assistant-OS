from ..base import CapabilityBase
from typing import Dict, Any, List

class TaskCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "task"

    @property
    def name(self) -> str: return "task"

    @property
    def actions(self) -> List[str]:
        return [
            "notes",
            "specialist",
            "scheduler.create",
            "scheduler.add_trigger",
            "scheduler.list",
            "scheduler.list_triggers",
            "scheduler.run",
            "scheduler.list_works",
        ]

    @staticmethod
    def _normalize_action(action_id: str) -> str:
        raw = (action_id or "").strip().lower()
        if raw.startswith("task."):
            raw = raw[5:]
        return raw

    @staticmethod
    def _ok(error_details: str = "", **extra) -> Dict[str, Any]:
        payload = {
            "ok": True,
            "success": True,
            "status": "success",
            "reason": None,
            "result_summary": str(error_details or "").strip() or "Task operation completed.",
            "structured_result": dict(extra),
            "artifacts": [],
            "attachment_delivery": {"status": "none", "confirmed": False},
            "freshness": {"status": "current", "source": "task_management"},
            "truncated": False,
            "requires_followup": False,
            "next_step_context": {},
            "diagnostics": {"capability": "task"},
            "error_details": error_details,
        }
        payload.update(extra)
        return payload

    @staticmethod
    def _err(code: str, error_details: str = "", **extra) -> Dict[str, Any]:
        payload = {
            "ok": False,
            "success": False,
            "status": "error",
            "error": code,
            "reason": code,
            "result_summary": str(error_details or "").strip() or "Task operation failed.",
            "structured_result": dict(extra),
            "artifacts": [],
            "attachment_delivery": {"status": "none", "confirmed": False},
            "freshness": {"status": "current", "source": "task_management"},
            "truncated": False,
            "requires_followup": False,
            "next_step_context": {},
            "diagnostics": {"capability": "task", "error": code},
            "error_details": error_details,
        }
        payload.update(extra)
        return payload

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = self._normalize_action(action_id)
        session = context.get("session")
        orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
        scheduler = getattr(self.kernel, "scheduler", None) if self.kernel else None
        
        if action == "notes":
            ss = getattr(orch, "scratchpad_service", None) if orch else None
            if not ss:
                return self._err("SCRATCHPAD_UNAVAILABLE", "Scratchpad service is not available.")
            cmd = params.get("command", "read")
            content = params.get("content", "")
            sid = session.session_id if session else None
            if cmd == 'read':
                return self._ok("Scratchpad content loaded.", content=ss.read(sid))
            if cmd == 'append' and content:
                ss.append(content, sid)
                return self._ok("Scratchpad appended.")
            if cmd == 'update' and content:
                ss.update(content, sid)
                return self._ok("Scratchpad updated.")
            if cmd == 'clear':
                ss.clear(sid)
                return self._ok("Scratchpad cleared.")
            return self._err("INVALID_NOTES_COMMAND", "Invalid notes command.", command=cmd)

        if action == "specialist":
            sm = getattr(orch, "specialist_manager", None) if orch else None
            if not sm:
                return self._err("SPECIALIST_UNAVAILABLE", "Specialist manager is not available.")
            name = str(params.get("name") or "").strip()
            if not name:
                return self._err("MISSING_NAME", "Specialist name is required.")
            if name in ['none', 'clear']:
                if session:
                    session.context['active_specialist'] = None
                return self._ok("Specialist deactivated.")
            if name.lower() in sm.list_specialists():
                if session:
                    session.context['active_specialist'] = name.lower()
                return self._ok(f"Specialist '{name}' activated.", specialist=name.lower())
            return self._err("SPECIALIST_NOT_FOUND", "Specialist not found.", specialist=name)

        if action == "scheduler.create":
            if not scheduler:
                return self._err("SCHEDULER_UNAVAILABLE", "Scheduler is not available.")
            name = str(params.get("name") or "").strip()
            task_context = str(params.get("context") or "").strip()
            if not name or not task_context:
                return self._err("MISSING_FIELDS", "Both 'name' and 'context' are required.")
            owner_session_id = str(params.get("owner_session_id") or (session.session_id if session else "")).strip() or None
            owner_sender_id = str(params.get("owner_sender_id") or "").strip() or None
            if not owner_sender_id and session and isinstance(getattr(session, "context", None), dict):
                principal_ctx = session.context.get("principal_context")
                if isinstance(principal_ctx, dict):
                    owner_sender_id = str(principal_ctx.get("sender_id") or "").strip() or None
            task = scheduler.create_task(
                name,
                task_context,
                owner_session_id=owner_session_id,
                owner_sender_id=owner_sender_id,
            )
            return self._ok("Task definition created.", task=task.to_dict())

        if action == "scheduler.add_trigger":
            if not scheduler:
                return self._err("SCHEDULER_UNAVAILABLE", "Scheduler is not available.")
            task_id = str(params.get("task_id") or "").strip()
            schedule_type = str(params.get("schedule_type") or "").strip().lower()
            schedule_value = params.get("schedule_value")
            holiday_rules = params.get("holiday_rules") if isinstance(params.get("holiday_rules"), dict) else {}
            if not task_id or not schedule_type or schedule_value is None:
                return self._err(
                    "MISSING_FIELDS",
                    "Fields 'task_id', 'schedule_type', and 'schedule_value' are required.",
                )
            if schedule_type not in {"interval", "cron", "date"}:
                return self._err("INVALID_SCHEDULE_TYPE", "schedule_type must be interval, cron, or date.")
            try:
                trigger = scheduler.add_trigger(task_id, schedule_type, schedule_value, holiday_rules=holiday_rules)
                return self._ok("Trigger created.", trigger=trigger.to_dict())
            except ValueError as e:
                return self._err("TASK_NOT_FOUND", str(e))
            except Exception as e:
                return self._err("TRIGGER_CREATE_FAILED", str(e))

        if action == "scheduler.list":
            if not scheduler:
                return self._err("SCHEDULER_UNAVAILABLE", "Scheduler is not available.")
            task_id = str(params.get("task_id") or "").strip()
            if task_id:
                task = scheduler.get_task(task_id)
                if not task:
                    return self._err("TASK_NOT_FOUND", "Task not found.", task_id=task_id)
                return self._ok("Task fetched.", task=task)
            return self._ok("Task list fetched.", tasks=scheduler.list_tasks())

        if action == "scheduler.list_triggers":
            if not scheduler:
                return self._err("SCHEDULER_UNAVAILABLE", "Scheduler is not available.")
            task_id = str(params.get("task_id") or "").strip()
            if not task_id:
                return self._ok("All triggers fetched.", triggers=scheduler.list_triggers())
            return self._ok("Task triggers fetched.", task_id=task_id, triggers=scheduler.list_triggers(task_id))

        if action == "scheduler.run":
            if not scheduler:
                return self._err("SCHEDULER_UNAVAILABLE", "Scheduler is not available.")
            task_id = str(params.get("task_id") or "").strip()
            if not task_id:
                return self._err("MISSING_TASK_ID", "Field 'task_id' is required.")
            task = scheduler.get_task(task_id)
            if not task:
                return self._err("TASK_NOT_FOUND", "Task not found.", task_id=task_id)
            scheduler.trigger_execution(task_id, trigger_id=None)
            return self._ok("Task execution triggered.", task_id=task_id)

        if action == "scheduler.list_works":
            if not scheduler:
                return self._err("SCHEDULER_UNAVAILABLE", "Scheduler is not available.")
            include_completed = bool(params.get("include_completed", False))
            owner_session_id = str(params.get("owner_session_id") or "").strip() or None
            favorite_session_id = str(params.get("favorite_session_id") or "").strip() or None
            session_id = str(params.get("session_id") or "").strip() or None
            limit = int(params.get("limit", 50))
            works = scheduler.list_works(
                include_completed=include_completed,
                session_id=session_id,
                owner_session_id=owner_session_id,
                favorite_session_id=favorite_session_id,
                limit=max(1, min(500, limit)),
                include_context=True,
            )
            return self._ok("Works listed.", works=works, count=len(works))

        return self._err("UNKNOWN_ACTION", f"Unknown task action: {action_id}")
