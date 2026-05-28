from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from ..auth import get_current_user
from ..core.models import User, AuditLog
from ..core.database import get_db
from sqlalchemy.orm import Session
from pydantic import BaseModel
import json
import os
import asyncio
import logging
import requests

# Logger for this module
logger = logging.getLogger("SystemRoutes")

router = APIRouter(prefix="/api/system", tags=["system"])

class CompressRequest(BaseModel):
    text: str

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
            "loaded_capabilities": sorted(list(getattr(kernel.capability_registry, "capabilities", {}).keys())),
            "failed_capabilities": getattr(getattr(kernel.orchestrator, "capability_loader", None), "failed_contracts", {}),
        }
    except HTTPException:
        return {"status": "starting", "message": "Kernel initializing"}

@router.get("/health")
def get_health(request: Request):
    """
    Returns detailed health status of LLM providers and other system components.
    """
    try:
        kernel = get_kernel(request)
        llm_health = getattr(kernel.llm_manager, "provider_health", {})
        
        # Sort by priority for consistent UI display
        sorted_llm = dict(sorted(llm_health.items(), key=lambda x: x[1].get("priority", 99)))
        
        return {
            "status": "ok",
            "llm": sorted_llm,
            "capabilities": {
                "total": len(getattr(kernel.capability_registry, "capabilities", {})),
                "failed": len(getattr(getattr(kernel.orchestrator, "capability_loader", None), "failed_contracts", {})),
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "error", "message": str(e)}

@router.get("/tunnels/status")
def get_tunnels_status(request: Request):
    """
    Returns the status of all active remote access tunnels (ngrok, cloudflare).
    """
    try:
        kernel = get_kernel(request)
        capabilities = getattr(kernel.capability_registry, "capabilities", {})
        
        tunnels = []
        for name in ["cloudflare_tunnel", "ngrok_tunnel"]:
            cap = capabilities.get(name)
            if cap:
                tunnels.append({
                    "id": name,
                    "provider": name.replace("_tunnel", ""),
                    "public_url": getattr(cap, "_public_url", None),
                    "status": "running" if getattr(cap, "_is_running", False) else "stopped",
                    "error": getattr(cap, "_last_error", None)
                })
        return {
            "status": "ok",
            "active_tunnels": tunnels
        }
    except Exception as e:
        logger.error(f"Failed to get tunnels status: {e}")
        return {"status": "error", "active_tunnels": []}

@router.get("/deezer/track/{track_id}")
def get_deezer_track(track_id: str, user: User = Depends(get_current_user)):
    """
    Server-side Deezer track proxy to avoid browser CORS issues.
    Returns normalized fields for the Dashboard mini-player.
    """
    safe_track_id = str(track_id or "").strip()
    if not safe_track_id.isdigit():
        raise HTTPException(status_code=400, detail="Invalid Deezer track id")

    try:
        resp = requests.get(f"https://api.deezer.com/track/{safe_track_id}", timeout=10)
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Deezer API HTTP {resp.status_code}")
        payload = resp.json() if resp.content else {}
        if isinstance(payload, dict) and payload.get("error"):
            msg = payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else "Deezer API error"
            raise HTTPException(status_code=502, detail=msg or "Deezer API error")

        album = payload.get("album") if isinstance(payload.get("album"), dict) else {}
        artist = payload.get("artist") if isinstance(payload.get("artist"), dict) else {}
        return {
            "id": str(payload.get("id") or safe_track_id),
            "title": str(payload.get("title") or ""),
            "artist": str(artist.get("name") or ""),
            "album": str(album.get("title") or ""),
            "cover": str(album.get("cover_big") or album.get("cover_medium") or album.get("cover") or ""),
            "preview": str(payload.get("preview") or ""),
            "link": str(payload.get("link") or f"https://www.deezer.com/track/{safe_track_id}"),
            "duration": int(payload.get("duration") or 30),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Deezer proxy error for track {safe_track_id}: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Deezer track metadata")

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

@router.post("/compress-personality")
async def compress_personality(req: CompressRequest, user: User = Depends(get_current_user), request: Request = None):
    """
    Compresses a natural language personality into a highly dense string using the LLM.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can compress personality")
    
    kernel = get_kernel(request)
    llm = kernel.llm_manager
    if not llm:
        raise HTTPException(status_code=503, detail="LLM Manager not available")

    prompt = (
        "Re-write the following personality profile into a highly condensed, dense, and telegraphic string of keywords and rules. "
        "Remove all conversational filler, greetings, and fluff. Preserve ALL constraints, behaviors, roles, and rules accurately. "
        "Keep it as short as possible without losing semantic instructions.\n\n"
        f"TEXT TO COMPRESS:\n{req.text}"
    )
    
    try:
        result = await asyncio.to_thread(
            llm.generate_text, 
            prompt=prompt, 
            system_prompt="You are an expert prompt compressor. Output ONLY the dense compressed text. Do not use conversational openings. Do not use markdown blocks.", 
            max_tokens=400
        )
        return {"compressed": str(result).strip()}
    except Exception as e:
        logger.error(f"Error compressing personality: {e}")
        raise HTTPException(status_code=500, detail="Failed to compress personality")

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

@router.get("/mcp/status")
def get_mcp_status(request: Request, user: User = Depends(get_current_user)):
    kernel = get_kernel(request)
    service = getattr(getattr(kernel, "orchestrator", None), "mcp_integration_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="MCP integration service not available")

    registry = getattr(service, "server_registry", None)
    servers = []
    if registry and hasattr(registry, "list_all"):
        for server in registry.list_all():
            resources = getattr(service, "resource_catalog_by_server", {}).get(server.id, {})
            servers.append(
                {
                    "id": server.id,
                    "title": server.title,
                    "enabled": bool(server.enabled),
                    "transport": {
                        "kind": str(server.transport.kind or ""),
                        "endpoint": str(server.transport.endpoint or ""),
                        "command": str(server.transport.command or ""),
                        "startup_timeout_s": float(server.transport.startup_timeout_s or 0),
                    },
                    "policy": {
                        "trust_tier": str(server.policy.trust_tier or ""),
                        "namespace": str(server.policy.namespace or ""),
                        "allow_tool_discovery": bool(server.policy.allow_tool_discovery),
                        "allow_resources": bool(server.policy.allow_resources),
                        "allow_prompts": bool(server.policy.allow_prompts),
                        "default_requires_approval": server.policy.default_requires_approval,
                        "tool_allowlist": list(server.policy.tool_allowlist or []),
                        "tool_denylist": list(server.policy.tool_denylist or []),
                    },
                    "resource_count": len(resources),
                }
            )
    return {
        "enabled": bool(getattr(service, "last_refresh_stats", {}).get("enabled", False)),
        "refresh": dict(getattr(service, "last_refresh_stats", {}) or {}),
        "servers": servers,
        "resources": service.list_discovered_resources() if hasattr(service, "list_discovered_resources") else [],
    }

@router.post("/mcp/refresh")
def refresh_mcp(request: Request, user: User = Depends(get_current_user)):
    kernel = get_kernel(request)
    service = getattr(getattr(kernel, "orchestrator", None), "mcp_integration_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="MCP integration service not available")
    try:
        return service.refresh()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh MCP integration: {e}")

@router.get("/mcp/resources")
def get_mcp_resources(request: Request, user: User = Depends(get_current_user), server_id: str = "", query: str = "", limit: int = 100):
    kernel = get_kernel(request)
    service = getattr(getattr(kernel, "orchestrator", None), "mcp_integration_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="MCP integration service not available")
    rows = service.list_discovered_resources(server_id=server_id)
    q = str(query or "").strip().lower()
    if q:
        rows = [
            row for row in rows
            if q in str(row.get("uri", "")).lower()
            or q in str(row.get("name", "")).lower()
            or q in str(row.get("title", "")).lower()
            or q in str(row.get("description", "")).lower()
        ]
    rows = rows[: max(1, min(int(limit or 100), 500))]
    return {"count": len(rows), "items": rows}

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
