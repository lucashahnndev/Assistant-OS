from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional, Any
import logging
import datetime
import os
import re
import json
from core.identity import PrincipalContext
from ..auth import get_current_user
from ..core.models import User

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
logger = logging.getLogger("TasksRoute")

# --- Pydantic Models ---
class TaskCreate(BaseModel):
    name: str
    context: str
    owner_session_id: Optional[str] = None
    owner_sender_id: Optional[str] = None

class NoteCreate(BaseModel):
    note: str

class TriggerCreate(BaseModel):
    task_id: str
    schedule_type: str # interval, cron, date
    schedule_value: Any
    holiday_rules: Optional[dict] = {}

class TriggerUpdate(BaseModel):
    enabled: bool

class WorkCommand(BaseModel):
    command: str
    payload: Optional[dict] = {}
    source_session_id: Optional[str] = None
    requester_session_id: Optional[str] = None

class WorkNote(BaseModel):
    note: str
    requester_session_id: Optional[str] = None

class WorkRestartRequest(BaseModel):
    requester_session_id: Optional[str] = None

# --- Helpers ---
def get_scheduler(request: Request):
    if not request.app.state.kernel:
        raise HTTPException(status_code=500, detail="Kernel not initialized")
    return request.app.state.kernel.scheduler

def _build_web_principal(user: User, requester_session_id: Optional[str] = None) -> PrincipalContext:
    sender_id = f"user_{user.id}"
    return PrincipalContext(
        interface="web",
        sender_id=sender_id,
        sender_name=user.username,
        session_id=(requester_session_id or sender_id),
    )

def _is_admin(user: User) -> bool:
    return str(getattr(user, "role", "")).lower() == "admin"

def _assert_work_access(request: Request, user: User, work_snapshot: dict, operation: str, requester_session_id: Optional[str] = None):
    if _is_admin(user):
        return
    ac = request.app.state.kernel.orchestrator.access_controller
    principal = _build_web_principal(user, requester_session_id=requester_session_id)
    if not ac.can_access_work(principal, work_snapshot, operation=operation):
        raise HTTPException(status_code=403, detail="You are not allowed to access this worker.")

def _assert_permission_decision_allowed(request: Request, principal: PrincipalContext):
    kernel = request.app.state.kernel
    allowed, reason = kernel.can_principal_control_permissions(principal)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"This principal is not allowed to control sensitive permission approvals ({reason}).",
        )

def _read_execution_log_tail(scheduler, execution_id: Optional[str], max_lines: int = 200, max_chars: int = 50000) -> dict:
    execution_id = str(execution_id or "").strip()
    if not execution_id:
        return {"execution_id": None, "available": False, "tail": "", "error_lines": []}

    log_path = os.path.join(scheduler.logs_dir, f"{execution_id}.log")
    if not os.path.exists(log_path):
        return {"execution_id": execution_id, "available": False, "tail": "", "error_lines": []}

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail_lines = lines[-max(1, int(max_lines)):]
        tail = "".join(tail_lines)
        if len(tail) > max_chars:
            tail = tail[-max_chars:]
        seen = set()
        error_lines = []
        for line in tail_lines:
            if not re.search(r"\b(error|exception|traceback|failed|fatal)\b", line, flags=re.IGNORECASE):
                continue
            clean = line.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            error_lines.append(clean)
        return {
            "execution_id": execution_id,
            "available": True,
            "tail": tail,
            "error_lines": error_lines[-80:],
        }
    except Exception as e:
        return {
            "execution_id": execution_id,
            "available": False,
            "tail": "",
            "error_lines": [f"Error reading log file: {str(e)}"],
        }

def _infer_issue_component(*parts: str) -> str:
    text = " ".join(str(p or "") for p in parts).lower()
    if any(t in text for t in ("planner", "plan_validation", "schema", "replan", "loop_guardrail", "plan")):
        return "planner"
    if any(t in text for t in ("llm", "model", "provider", "prompt", "token", "refusal", "completion")):
        return "llm"
    if any(t in text for t in ("tool", "capability", "dispatch", "driver", "browser.control", "action_dispatch")):
        return "tool"
    return "worker"

def _extract_worker_errors(events: List[dict], row: Optional[dict] = None, limit: int = 80) -> List[dict]:
    out = []

    issue_tokens = (
        "fail",
        "error",
        "exception",
        "recovery_needed",
        "replanning",
        "replan",
        "validation",
        "schema",
        "loop_guardrail",
        "failure_guardrail",
        "action_dispatch_failure",
        "planner_output_invalid",
        "llm_error",
        "refusal",
        "timeout",
    )

    for event in events:
        if not isinstance(event, dict):
            continue
        name = str(event.get("event") or "").strip()
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        name_l = name.lower()
        status_l = str(payload.get("status") or "").lower()
        error_code = str(
            payload.get("error_code")
            or payload.get("code")
            or payload.get("result_reason")
            or ""
        ).strip()
        category = str(payload.get("category") or payload.get("error_category") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        summary = str(payload.get("summary") or payload.get("failure_summary") or "").strip()
        details = str(payload.get("details") or "").strip()

        raw_text = " ".join((name_l, status_l, error_code.lower(), reason.lower(), summary.lower(), details.lower()))
        is_error = (
            any(token in raw_text for token in issue_tokens)
            or status_l in {"failed", "failure", "error", "recovery", "replanning", "stalled"}
            or bool(error_code)
        )
        if not is_error:
            continue
        message = (
            payload.get("error")
            or payload.get("message")
            or payload.get("details")
            or payload.get("reason")
            or payload.get("exception")
            or payload.get("failure_summary")
            or payload.get("summary")
            or ""
        )
        if not isinstance(message, str):
            try:
                message = json.dumps(message, ensure_ascii=False)
            except Exception:
                message = str(message)
        severity = "error"
        lowered_name = name_l
        if "fatal" in raw_text:
            severity = "fatal"
        elif "warning" in raw_text or "slow" in lowered_name:
            severity = "warning"
        component = _infer_issue_component(name, error_code, reason, summary, details, payload.get("source"), payload.get("component"))
        out.append(
            {
                "ts": event.get("ts"),
                "event": name or "worker_event",
                "message": str(message or "").strip()[:1200],
                "payload": payload,
                "severity": severity,
                "component": component,
                "error_code": error_code or None,
                "category": category or None,
            }
        )

    # Add context-level synthetic diagnostics (e.g., last_error in summary/data).
    row_ctx = row.get("context") if isinstance(row, dict) and isinstance(row.get("context"), dict) else {}
    row_summary = row_ctx.get("summary") if isinstance(row_ctx.get("summary"), dict) else {}
    row_data = row_ctx.get("data") if isinstance(row_ctx.get("data"), dict) else {}
    last_error = str(row_summary.get("last_error") or row_data.get("last_error") or "").strip()
    if last_error and last_error.lower() not in {"none", "null", "n/a"}:
        out.append(
            {
                "ts": row_ctx.get("updated_at") or row.get("updated_at") if isinstance(row, dict) else None,
                "event": "context_last_error",
                "message": last_error[:1200],
                "payload": {"source": "context.summary.last_error"},
                "severity": "error",
                "component": _infer_issue_component(last_error),
                "error_code": None,
                "category": None,
            }
        )

    return out[-max(1, int(limit)):]

# --- Task Definitions ---
@router.get("/definitions")
def list_task_definitions(request: Request, user: User = Depends(get_current_user)):
    """List all task blueprints"""
    return get_scheduler(request).list_tasks()

@router.post("/definitions")
def create_task_definition(task: TaskCreate, request: Request, user: User = Depends(get_current_user)):
    """Create a new task blueprint"""
    default_sender = f"user_{user.id}"
    new_task = get_scheduler(request).create_task(
        task.name,
        task.context,
        owner_session_id=task.owner_session_id,
        owner_sender_id=(task.owner_sender_id or default_sender),
    )
    return new_task.to_dict()

@router.get("/definitions/{task_id}")
def get_task_details(task_id: str, request: Request, user: User = Depends(get_current_user)):
    """Get specific task details"""
    task = get_scheduler(request).get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.delete("/definitions/{task_id}")
def delete_task_definition(task_id: str, request: Request, user: User = Depends(get_current_user)):
    """Delete a task and its triggers"""
    get_scheduler(request).delete_task(task_id)
    return {"status": "deleted", "task_id": task_id}

# --- Task Notes ---
@router.post("/definitions/{task_id}/notes")
def add_task_note(task_id: str, note: NoteCreate, request: Request, user: User = Depends(get_current_user)):
    """Add a note to a task"""
    get_scheduler(request).add_task_note(task_id, note.note)
    return {"status": "note_added"}

# --- Scheule Triggers ---
@router.get("/definitions/{task_id}/triggers")
def list_task_triggers(task_id: str, request: Request, user: User = Depends(get_current_user)):
    """List triggers for a specific task"""
    return get_scheduler(request).list_triggers(task_id)

@router.post("/triggers")
def create_trigger(trigger: TriggerCreate, request: Request, user: User = Depends(get_current_user)):
    """Add a schedule trigger to a task"""
    try:
        new_trigger = get_scheduler(request).add_trigger(
            task_id=trigger.task_id,
            schedule_type=trigger.schedule_type,
            schedule_value=trigger.schedule_value,
            holiday_rules=trigger.holiday_rules
        )
        return new_trigger.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/triggers/{trigger_id}")
def delete_trigger(trigger_id: str, request: Request, user: User = Depends(get_current_user)):
    """Delete a trigger"""
    get_scheduler(request).delete_trigger(trigger_id)
    return {"status": "deleted", "trigger_id": trigger_id}

@router.post("/triggers/{trigger_id}/toggle")
def toggle_trigger(trigger_id: str, update: TriggerUpdate, request: Request, user: User = Depends(get_current_user)):
    """Enable/Disable a trigger"""
    get_scheduler(request).toggle_trigger(trigger_id, update.enabled)
    return {"status": "updated", "trigger_id": trigger_id, "enabled": update.enabled}

# --- Execution / History ---
@router.post("/definitions/{task_id}/run")
def run_task_manually(task_id: str, request: Request, user: User = Depends(get_current_user)):
    """Manually trigger a task execution"""
    get_scheduler(request).trigger_execution(task_id, trigger_id=None)
    return {"status": "triggered", "task_id": task_id}

@router.get("/definitions/{task_id}/executions")
def list_task_history(task_id: str, request: Request, user: User = Depends(get_current_user)):
    """List execution history for a task"""
    # Sort by start_time desc
    history = get_scheduler(request).list_executions(task_id)
    history.sort(key=lambda x: x['start_time'], reverse=True)
    return history

@router.get("/executions/{execution_id}/logs")
def get_execution_logs(execution_id: str, request: Request, user: User = Depends(get_current_user)):
    """Get logs for a specific execution"""
    # This is inefficient for large logs, but sufficient for now.
    # Ideally should support pagination or streaming.
    scheduler = get_scheduler(request)
    
    # We have to find the execution in the scheduler
    # Scheduler doesn't have get_execution(id) exposed directly but we can iterate or add it
    # But list_executions returns dicts.
    
    # Let's add get_execution to scheduler public API? 
    # Or just access internal map via a new method or list.
    # Accessing internal map from here is risky if not locked.
    
    # Let's iterate list_executions for now (safe but slow if thousands)
    # Or better: The scheduler has .executions dict.
    # We should add a helper in scheduler. 
    # But for now, let's just peek into scheduler.executions if we can access it safely?
    # No, use lock.
    
    # Let's assume we add get_execution_by_id to scheduler in next step if needed.
    # But wait, I can just use list_executions(task_id=None) and filter?
    
    # Actually, let's just add the method to scheduler in the same file if possible?
    # No, I can't edit scheduler.py here.
    
    # Let's implement a workaround: access scheduler.executions with lock? 
    # interacting with scheduler private members is bad.
    
    # I will assume `list_executions` returns everything and I filter.
    # Not optimal.
    
    # Let's try to access the file directly if we know the path pattern?
    # We know it is in `data/execution_logs/{id}.log`
    
    log_path = os.path.join(scheduler.logs_dir, f"{execution_id}.log")
    
    if not os.path.exists(log_path):
        return {"logs": "Log file not found or execution hasn't started logging yet."}
        
    try:
        with open(log_path, "r") as f:
            content = f.read()
        return {"logs": content}
    except Exception as e:
        return {"logs": f"Error reading logs: {str(e)}"}

@router.post("/executions/{execution_id}/cancel")
def cancel_execution(execution_id: str, request: Request, user: User = Depends(get_current_user)):
    """Cancel a running execution"""
    get_scheduler(request).cancel_execution(execution_id)
    return {"status": "cancellation_requested", "execution_id": execution_id}

# --- Works Monitoring (Unified view for ad-hoc + scheduled executions) ---
@router.get("/works")
def list_works(
    request: Request,
    include_completed: bool = False,
    session_id: Optional[str] = None,
    owner_session_id: Optional[str] = None,
    favorite_session_id: Optional[str] = None,
    limit: int = 200,
    requester_session_id: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    scheduler = get_scheduler(request)
    rows = scheduler.list_works(
        include_completed=include_completed,
        session_id=session_id,
        owner_session_id=owner_session_id,
        favorite_session_id=favorite_session_id,
        limit=limit,
        include_context=True,
    )
    if _is_admin(user):
        return rows
    ac = request.app.state.kernel.orchestrator.access_controller
    principal = _build_web_principal(user, requester_session_id=requester_session_id)
    return [row for row in rows if ac.can_access_work(principal, row, operation="view")]

@router.get("/works/{work_id}")
def get_work(work_id: str, request: Request, requester_session_id: Optional[str] = None, user: User = Depends(get_current_user)):
    scheduler = get_scheduler(request)
    row = scheduler.get_work_snapshot(work_id, include_context=True)
    if not row:
        raise HTTPException(status_code=404, detail="Work not found")
    _assert_work_access(request, user, row, operation="view", requester_session_id=requester_session_id)
    return row

@router.post("/works/{work_id}/commands")
def send_work_command(work_id: str, body: WorkCommand, request: Request, user: User = Depends(get_current_user)):
    scheduler = get_scheduler(request)
    row = scheduler.get_work_snapshot(work_id, include_context=True)
    if not row:
        raise HTTPException(status_code=404, detail="Work not found")
    _assert_work_access(request, user, row, operation="control", requester_session_id=body.requester_session_id)
    if str(body.command or "").strip().lower() in {"approve", "deny"}:
        _assert_permission_decision_allowed(
            request,
            _build_web_principal(user, requester_session_id=body.requester_session_id),
        )

    source = body.source_session_id or body.requester_session_id or f"user_{user.id}"
    ok = scheduler.push_work_command(
        work_id=work_id,
        command=body.command,
        payload=body.payload or {},
        source_session_id=source,
    )
    return {"status": "accepted", "work_id": work_id, "command": body.command}

@router.post("/works/{work_id}/pause")
def pause_work(work_id: str, request: Request, requester_session_id: Optional[str] = None, user: User = Depends(get_current_user)):
    scheduler = get_scheduler(request)
    row = scheduler.get_work_snapshot(work_id, include_context=True)
    if not row:
        raise HTTPException(status_code=404, detail="Work not found")
    _assert_work_access(request, user, row, operation="control", requester_session_id=requester_session_id)
    scheduler.push_work_command(
        work_id=work_id,
        command="pause",
        payload={"reason": "Paused from web"},
        source_session_id=requester_session_id or f"user_{user.id}",
    )
    return {"status": "accepted", "work_id": work_id, "command": "pause"}

@router.post("/works/{work_id}/resume")
def resume_work(work_id: str, request: Request, requester_session_id: Optional[str] = None, user: User = Depends(get_current_user)):
    scheduler = get_scheduler(request)
    row = scheduler.get_work_snapshot(work_id, include_context=True)
    if not row:
        raise HTTPException(status_code=404, detail="Work not found")
    _assert_work_access(request, user, row, operation="control", requester_session_id=requester_session_id)
    scheduler.push_work_command(
        work_id=work_id,
        command="resume",
        payload={"reason": "Resumed from web"},
        source_session_id=requester_session_id or f"user_{user.id}",
    )
    return {"status": "accepted", "work_id": work_id, "command": "resume"}

@router.post("/works/{work_id}/restart")
def restart_work(work_id: str, body: WorkRestartRequest, request: Request, user: User = Depends(get_current_user)):
    scheduler = get_scheduler(request)
    row = scheduler.get_work_snapshot(work_id, include_context=True)
    if not row:
        raise HTTPException(status_code=404, detail="Work not found")

    requester_session_id = body.requester_session_id
    _assert_work_access(request, user, row, operation="control", requester_session_id=requester_session_id)

    input_text = str(row.get("input_text") or "").strip()
    if not input_text:
        ctx = row.get("context") if isinstance(row.get("context"), dict) else {}
        input_text = str(ctx.get("input_text") or "").strip()
    if not input_text:
        raise HTTPException(status_code=400, detail="This work has no input text to restart")

    session_id = str(row.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="This work has no target session to restart")

    kernel = request.app.state.kernel
    if not kernel:
        raise HTTPException(status_code=503, detail="Kernel not initialized")

    server_driver = next((d for d in kernel.drivers if hasattr(d, "app")), None)
    if not server_driver:
        raise HTTPException(status_code=500, detail="ServerDriver not found to restart work")

    principal = PrincipalContext(
        interface="web",
        sender_id=f"user_{user.id}",
        sender_name=user.username,
        session_id=session_id,
    )

    new_work_id = kernel.process_input(
        input_text,
        server_driver,
        user_id=session_id,
        user_data={
            "user_name": user.display_name or user.username,
            "portal_user_id": user.id,
            "portal_username": user.username,
            "restart_from_work_id": work_id,
        },
        context=principal,
    )

    return {
        "status": "accepted",
        "work_id": work_id,
        "restarted_work_id": new_work_id,
        "session_id": session_id,
    }

@router.post("/works/{work_id}/queue_message")
def queue_work_message(work_id: str, body: WorkNote, request: Request, user: User = Depends(get_current_user)):
    scheduler = get_scheduler(request)
    row = scheduler.get_work_snapshot(work_id, include_context=True)
    if not row:
        raise HTTPException(status_code=404, detail="Work not found")
    _assert_work_access(request, user, row, operation="control", requester_session_id=body.requester_session_id)
    scheduler.push_work_command(
        work_id=work_id,
        command="inject_message",
        payload={"message": body.note},
        source_session_id=body.requester_session_id or f"user_{user.id}",
    )
    return {"status": "accepted", "work_id": work_id, "command": "inject_message"}

@router.post("/works/{work_id}/direct_message")
def direct_work_message(work_id: str, body: WorkNote, request: Request, user: User = Depends(get_current_user)):
    scheduler = get_scheduler(request)
    row = scheduler.get_work_snapshot(work_id, include_context=True)
    if not row:
        raise HTTPException(status_code=404, detail="Work not found")
    _assert_work_access(request, user, row, operation="control", requester_session_id=body.requester_session_id)
    source = body.requester_session_id or f"user_{user.id}"
    scheduler.push_work_command(work_id=work_id, command="pause", payload={"reason": "Direct message mode"}, source_session_id=source)
    scheduler.push_work_command(work_id=work_id, command="inject_message", payload={"message": body.note}, source_session_id=source)
    return {"status": "accepted", "work_id": work_id, "command": "pause+inject_message"}

@router.post("/works/{work_id}/notes")
def append_work_note(work_id: str, body: WorkNote, request: Request, user: User = Depends(get_current_user)):
    scheduler = get_scheduler(request)
    row = scheduler.get_work_snapshot(work_id, include_context=True)
    if not row:
        raise HTTPException(status_code=404, detail="Work not found")
    _assert_work_access(request, user, row, operation="control", requester_session_id=body.requester_session_id)
    ctx = scheduler.get_work_context(work_id) if hasattr(scheduler, "get_work_context") else {}
    notes = []
    if isinstance(ctx.get("notes"), list):
        notes = list(ctx.get("notes"))
    notes.append({"ts": datetime.datetime.now().isoformat(), "author": f"user_{user.id}", "text": body.note})
    scheduler.update_work_context(work_id, {"notes": notes[-300:]})
    return {"status": "saved", "work_id": work_id, "notes_count": len(notes)}

@router.get("/works/{work_id}/events")
def get_work_events(
    work_id: str,
    request: Request,
    limit: int = 200,
    requester_session_id: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    scheduler = get_scheduler(request)
    row = scheduler.get_work_snapshot(work_id, include_context=True)
    if not row:
        raise HTTPException(status_code=404, detail="Work not found")
    _assert_work_access(request, user, row, operation="view", requester_session_id=requester_session_id)
    events = scheduler.read_work_events(work_id, limit=max(1, min(2000, int(limit))))
    return {"work_id": work_id, "events": events, "count": len(events)}

@router.get("/works/{work_id}/overwatch")
def get_work_overwatch(
    work_id: str,
    request: Request,
    events_limit: int = 200,
    requester_session_id: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    scheduler = get_scheduler(request)
    row = scheduler.get_work_snapshot(work_id, include_context=True)
    if not row:
        raise HTTPException(status_code=404, detail="Work not found")
    _assert_work_access(request, user, row, operation="view", requester_session_id=requester_session_id)

    ctx = row.get("context") if isinstance(row.get("context"), dict) else {}
    data = ctx.get("data") if isinstance(ctx.get("data"), dict) else {}
    summary = ctx.get("summary") if isinstance(ctx.get("summary"), dict) else {}
    planner = ctx.get("planner") if isinstance(ctx.get("planner"), dict) else {}
    task_id = data.get("task_id")
    executions = scheduler.list_executions(task_id) if task_id else []
    triggers = scheduler.list_triggers(task_id) if task_id else []
    events = scheduler.read_work_events(work_id, limit=max(1, min(2000, int(events_limit))))
    worker_errors = _extract_worker_errors(events, row=row)
    recent_executions = sorted(
        executions,
        key=lambda row: str(row.get("start_time") or ""),
        reverse=True,
    )[:20]
    latest_execution_id = (
        data.get("execution_id")
        or (recent_executions[0].get("execution_id") if recent_executions else None)
    )
    latest_execution_logs = _read_execution_log_tail(scheduler, latest_execution_id)

    return {
        "work": row,
        "summary": summary,
        "planner": planner,
        "capabilities_used": data.get("capabilities_used", []),
        "actions_used": data.get("actions_used", []),
        "media_used": data.get("media_used", []),
        "sources_used": data.get("sources_used", []),
        "queued_messages": data.get("queued_messages", []),
        "origin": {
            "session_id": row.get("session_id"),
            "owner_session_id": row.get("owner_session_id"),
            "favorite_session_id": row.get("favorite_session_id"),
            "owner_sender_id": row.get("owner_sender_id"),
            "favorite_sender_id": row.get("favorite_sender_id"),
        },
        "task": {
            "task_id": task_id,
            "execution_count": len(executions),
            "trigger_count": len(triggers),
            "triggers": triggers[:20],
        },
        "recent_executions": recent_executions,
        "events": events,
        "worker_errors": worker_errors,
        "latest_execution_logs": latest_execution_logs,
    }

@router.get("/sessions/{session_id}")
def list_session_tasks(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """Lists all tasks registered in a specific session's registry."""
    kernel = request.app.state.kernel
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.task_registry

@router.get("/active")
def list_active_works(request: Request, requester_session_id: Optional[str] = None, user: User = Depends(get_current_user)):
    """List active works."""
    scheduler = get_scheduler(request)
    rows = scheduler.list_works(include_completed=False, include_context=True)
    if _is_admin(user):
        return rows
    ac = request.app.state.kernel.orchestrator.access_controller
    principal = _build_web_principal(user, requester_session_id=requester_session_id)
    return [row for row in rows if ac.can_access_work(principal, row, operation="view")]
