from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional, Any
import logging

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
logger = logging.getLogger("TasksRoute")

# --- Pydantic Models ---
class TaskCreate(BaseModel):
    name: str
    context: str

class NoteCreate(BaseModel):
    note: str

class TriggerCreate(BaseModel):
    task_id: str
    schedule_type: str # interval, cron, date
    schedule_value: Any
    holiday_rules: Optional[dict] = {}

class TriggerUpdate(BaseModel):
    enabled: bool

# --- Helpers ---
def get_scheduler(request: Request):
    if not request.app.state.kernel:
        raise HTTPException(status_code=500, detail="Kernel not initialized")
    return request.app.state.kernel.scheduler

# --- Task Definitions ---
@router.get("/definitions")
def list_task_definitions(request: Request):
    """List all task blueprints"""
    return get_scheduler(request).list_tasks()

@router.post("/definitions")
def create_task_definition(task: TaskCreate, request: Request):
    """Create a new task blueprint"""
    new_task = get_scheduler(request).create_task(task.name, task.context)
    return new_task.to_dict()

@router.get("/definitions/{task_id}")
def get_task_details(task_id: str, request: Request):
    """Get specific task details"""
    task = get_scheduler(request).get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.delete("/definitions/{task_id}")
def delete_task_definition(task_id: str, request: Request):
    """Delete a task and its triggers"""
    get_scheduler(request).delete_task(task_id)
    return {"status": "deleted", "task_id": task_id}

# --- Task Notes ---
@router.post("/definitions/{task_id}/notes")
def add_task_note(task_id: str, note: NoteCreate, request: Request):
    """Add a note to a task"""
    get_scheduler(request).add_task_note(task_id, note.note)
    return {"status": "note_added"}

# --- Scheule Triggers ---
@router.get("/definitions/{task_id}/triggers")
def list_task_triggers(task_id: str, request: Request):
    """List triggers for a specific task"""
    return get_scheduler(request).list_triggers(task_id)

@router.post("/triggers")
def create_trigger(trigger: TriggerCreate, request: Request):
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
def delete_trigger(trigger_id: str, request: Request):
    """Delete a trigger"""
    get_scheduler(request).delete_trigger(trigger_id)
    return {"status": "deleted", "trigger_id": trigger_id}

@router.post("/triggers/{trigger_id}/toggle")
def toggle_trigger(trigger_id: str, update: TriggerUpdate, request: Request):
    """Enable/Disable a trigger"""
    get_scheduler(request).toggle_trigger(trigger_id, update.enabled)
    return {"status": "updated", "trigger_id": trigger_id, "enabled": update.enabled}

# --- Execution / History ---
@router.post("/definitions/{task_id}/run")
def run_task_manually(task_id: str, request: Request):
    """Manually trigger a task execution"""
    get_scheduler(request).trigger_execution(task_id, trigger_id=None)
    return {"status": "triggered", "task_id": task_id}

@router.get("/definitions/{task_id}/executions")
def list_task_history(task_id: str, request: Request):
    """List execution history for a task"""
    # Sort by start_time desc
    history = get_scheduler(request).list_executions(task_id)
    history.sort(key=lambda x: x['start_time'], reverse=True)
    return history

@router.get("/executions/{execution_id}/logs")
def get_execution_logs(execution_id: str, request: Request):
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
    
    import os
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
def cancel_execution(execution_id: str, request: Request):
    """Cancel a running execution"""
    get_scheduler(request).cancel_execution(execution_id)
    return {"status": "cancellation_requested", "execution_id": execution_id}

# --- Legacy / Active Works (Optional compatibility) ---
# Keeping this if the frontend dashboard still uses it for "Running Agents"
@router.get("/active")
def list_active_works(request: Request):
    """List currently active kernel processes (Agents)"""
    return get_scheduler(request).list_active_works()
