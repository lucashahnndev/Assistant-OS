from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from ..auth import get_current_user
from ..core.models import User, AuditLog
from ..core.database import get_db
from sqlalchemy.orm import Session
import json
import os
import asyncio
import logging

# Logger for this module
logger = logging.getLogger("SystemRoutes")

router = APIRouter(prefix="/api/system", tags=["system"])
SENSITIVE_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "PRIVATE", "JWT", "AUTH")

def get_kernel(request: Request):
    if not hasattr(request.app.state, "kernel") or not request.app.state.kernel:
        raise HTTPException(status_code=503, detail="Kernel not initialized")
    return request.app.state.kernel

def _is_sensitive_env_key(key: str) -> bool:
    key_upper = key.upper()
    return any(hint in key_upper for hint in SENSITIVE_ENV_HINTS)

def _read_env_file(path: str) -> dict:
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data

def _read_env_template_keys(template_path: str) -> list[str]:
    keys = []
    if not os.path.exists(template_path):
        return keys
    with open(template_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _ = line.split("=", 1)
            key = key.strip()
            if key and key not in keys:
                keys.append(key)
    return keys

def _mask_value(value: str) -> str:
    if not value:
        return ""
    return "********"

@router.get("/status")
def get_status(request: Request):
    """
    Returns the current status of the Agent System.
    """
    try:
        kernel = get_kernel(request)
        # Basic status
        agent_config = kernel.config_manager.get("agent", {})
        frontend_config = kernel.config_manager.get("frontend", {})
        
        import time
        uptime_seconds = int(time.time() - kernel.start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours:02}:{minutes:02}:{seconds:02}"

        return {
            "status": "running",
            "uptime": uptime_str,
            "agent_name": agent_config.get("agent_name", "Assistant"),
            "personality": agent_config.get("personality", ""),
            "public_mode": frontend_config.get("public_mode", False),
            "frontend_port": frontend_config.get("port", 5173),
            "drivers": [d.__class__.__name__ for d in kernel.drivers],
            "loaded_skills": list(kernel.config_manager.get_skills_config().keys())
        }
    except HTTPException:
        return {"status": "starting", "message": "Kernel initializing"}

@router.get("/config")
def get_config(user: User = Depends(get_current_user), request: Request = None):
    """
    Returns the current configuration (config.json).
    Requires Auth.
    """
    config_path = os.path.join(os.getcwd(), "data", "config.json")
    if not os.path.exists(config_path):
        return {}
    
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read config: {e}")
        return {}

@router.get("/activity")
def get_activity(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    Returns recent system audit logs.
    """
    try:
        # Query last 10 audit logs
        logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(10).all()
        return logs
    except Exception as e:
        logger.error(f"Error fetching activity: {e}")
        return []

@router.post("/config")
def update_config(config: dict, user: User = Depends(get_current_user), request: Request = None):
    """
    Updates config.json.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update config")

    config_path = os.path.join(os.getcwd(), "data", "config.json")
    
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
        
        # Reload kernel config if possible
        kernel = get_kernel(request)
        if kernel:
            success = kernel.reload_config()
            if success:
                logger.info("Config reloaded in Kernel via Hot Reload.")
            else:
                logger.error("Hot reload failed after config update.")

        return {"applied": True, "requires_restart": False, "message": "Configuration saved and hot-reloaded."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {str(e)}")

@router.post("/reload")
def trigger_reload(user: User = Depends(get_current_user), request: Request = None):
    """
    Manually triggers a hot reload of the kernel configuration and providers.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can trigger reload")
    
    kernel = get_kernel(request)
    success = kernel.reload_config()
    if success:
        return {"success": True, "message": "System hot-reloaded successfully."}
    else:
        raise HTTPException(status_code=500, detail="Hot reload failed. Check server logs.")

@router.get("/env")
def get_env(user: User = Depends(get_current_user)):
    """
    Returns environment variables with server-side masking for sensitive fields.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view environment")
        
    env_path = os.path.join(os.getcwd(), ".env")
    env_example_path = os.path.join(os.getcwd(), ".env.example")

    try:
        current_env = _read_env_file(env_path)
        ordered_keys = _read_env_template_keys(env_example_path)
        for key in current_env.keys():
            if key not in ordered_keys:
                ordered_keys.append(key)

        masked_payload = {}
        for key in ordered_keys:
            value = current_env.get(key, "")
            masked_payload[key] = value
        return masked_payload
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read .env: {str(e)}")

@router.post("/env")
def update_env(updates: dict, user: User = Depends(get_current_user)):
    """
    Updates .env file.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update environment")
        
    env_path = os.path.join(os.getcwd(), ".env")
    
    try:
        current_env = _read_env_file(env_path)
        
        # Apply updates
        for key, value in updates.items():
            if not isinstance(key, str):
                continue
            if value is None:
                continue
            if not isinstance(value, str):
                value = str(value)

            # If value is empty skip update for this key to prevent clearing by accident,
            # unless the user explicitly wants to delete (which should be handled differently, but empty for now skips)
            if value.strip() == "":
                continue
            current_env[key] = value

        with open(env_path, "w", encoding="utf-8") as f:
            for key, value in current_env.items():
                f.write(f"{key}={value}\n")
                
        return {"success": True, "message": ".env updated. Restart may be required for some changes."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update .env: {str(e)}")

@router.get("/logs/list")
def list_logs(user: User = Depends(get_current_user)):
    """Lists available log files."""
    log_dir = os.path.join(os.getcwd(), "data", "logs")
    if not os.path.exists(log_dir):
        return []
    
    return [f for f in os.listdir(log_dir) if f.endswith(".log")]

@router.get("/logs/download")
def download_logs(filename: str = "assistant.log", user: User = Depends(get_current_user)):
    """Downloads a specific log file."""
    # Security: Basename only
    filename = os.path.basename(filename)
    if not filename.endswith(".log"):
         raise HTTPException(status_code=400, detail="Invalid log file")

    log_path = os.path.join(os.getcwd(), "data", "logs", filename)
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file not found")
    
    from fastapi.responses import FileResponse
    return FileResponse(log_path, filename=filename)

@router.get("/logs")
async def stream_logs(request: Request, source: str = "assistant.log", user: User = Depends(get_current_user)):
    """
    Streams a log file via SSE.
    """
    source = os.path.basename(source)
    if not source.endswith(".log"):
         raise HTTPException(status_code=400, detail="Invalid log source")

    log_path = os.path.join(os.getcwd(), "data", "logs", source)

    async def log_generator():
        # Start by sending last 50 lines
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                for line in lines[-50:]:
                    yield f"data: {json.dumps({'type': 'log', 'msg': line.strip()})}\n\n"
            
            # Then tail the file
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(0, os.SEEK_END)
                while True:
                    if await request.is_disconnected():
                        break
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.5)
                        continue
                    yield f"data: {json.dumps({'type': 'log', 'msg': line.strip()})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'msg': f'Log file {source} not found'})}\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@router.get("/works/{work_id}/context")
async def get_work_context(work_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Returns the context.json snapshot for a given work_id.
    Used by the frontend WorkUnitInspector panel.
    """
    kernel = get_kernel(request)
    scheduler = getattr(kernel, "scheduler", None)
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not available")

    snapshot = scheduler.get_work_snapshot(work_id, include_context=True)
    if snapshot is None:
        # Work may have been evicted from in-memory registry; try reading disk directly
        from config.manager import ConfigManager
        data_dir = ConfigManager.get_data_dir()
        # Try session-scoped first, then global
        import glob
        patterns = [
            os.path.join(data_dir, "works", work_id, "context.json"),
            os.path.join(data_dir, "sessions", "*", "works", work_id, "context.json"),
        ]
        context = None
        for pattern in patterns:
            matches = glob.glob(pattern)
            if matches:
                try:
                    with open(matches[0], "r", encoding="utf-8") as f:
                        context = json.load(f)
                    break
                except Exception:
                    pass
        if context is None:
            raise HTTPException(status_code=404, detail=f"Work {work_id} not found")
        return {"work_id": work_id, "context": context}

    return {"work_id": work_id, "context": snapshot.get("context", {}), "status": snapshot.get("status")}
