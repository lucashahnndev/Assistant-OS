from fastapi import APIRouter, Depends, HTTPException, Request, File, UploadFile
from fastapi.responses import StreamingResponse, FileResponse, Response
from core.identity import PrincipalContext
from ..auth import get_current_user
from ..core.models import User, AuditLog
from ..core.database import get_db
from sqlalchemy.orm import Session
import logging
import json
import os
import shutil

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
logger = logging.getLogger("SessionsRoutes")

def get_kernel(request: Request):
    if not hasattr(request.app.state, "kernel") or not request.app.state.kernel:
        raise HTTPException(status_code=503, detail="Kernel not initialized")
    return request.app.state.kernel

@router.get("")
@router.get("/")
def list_sessions(request: Request, interface: str = "all", user: User = Depends(get_current_user)):
    """
    List all sessions for an interface, ordered by last_opened_at.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    return orch.get_sessions_list(interface)

@router.get("/active")
def get_active_session(request: Request, interface: str = "web", user: User = Depends(get_current_user)):
    """
    Get the session that should be opened automatically.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_active_session(interface)
    if not session:
        return {"id": None, "source": interface, "is_new": True}
        
    return {
        "id": session.session_id,
        "source": session.source,
        "is_new": False
    }

@router.post("")
@router.post("/")
def create_session(request: Request, payload: dict = None, user: User = Depends(get_current_user)):
    """
    Create a new session.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    interface = payload.get("interface", "web") if payload else "web"
    name = payload.get("name", "") if payload else ""
    import uuid
    # Enforce naming convention: if web, prefix with web-
    session_id = f"{interface}-{str(uuid.uuid4())[:8]}"
    
    session = orch.create_session(session_id, interface, name=name)
    
    return {"id": session_id, "source": interface, "name": name}

@router.post("/{session_id}/open")
def open_session(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Mark a session as recently opened.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.open_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    return {"status": "success", "session_id": session_id, "last_opened_at": session.last_opened_at}

@router.get("/{session_id}")
def get_session(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Get session state and only the most recent history for initial load.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        # If it's a new lazy session search, avoid 500
        return {"id": session_id, "source": "web", "name": "", "history": [], "is_new": True}

    # Timeline source of truth must be chat.json (not session.json context snapshot).
    history = orch.get_chat_history(session_id)

    return {
        "id": session.session_id,
        "session_id": session.session_id,
        "source": getattr(session, 'source', 'web'),
        "interface": getattr(session, 'source', 'web'),
        "name": getattr(session, 'name', ''),
        "profile_picture": getattr(session, 'profile_picture', None),
        "history": history[-15:] if len(history) > 15 else history,
        "context": session.context,
        "scratchpad": session.scratchpad
    }

@router.patch("/{session_id}")
def update_session(session_id: str, payload: dict, request: Request, user: User = Depends(get_current_user)):
    """
    Update session properties like name.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    if "name" in payload:
        session.name = payload["name"]
        
        # Persist the change
        orch._save_session(session)
        
        # Notify web sockets if needed
        from utils.event_bus import global_event_bus
        global_event_bus.emit_threadsafe({
            "type": "session_updated",
            "session_id": session.session_id,
            "name": session.name
        })
        
    return {"status": "success", "session_id": session.session_id, "name": session.name}

@router.put("/{session_id}/read")
def mark_session_read(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """Marks all assistant messages in a session as read."""
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    if session.mark_as_read("assistant"):
        orch._save_session(session)
        # Notify via event bus that unread count changed
        from utils.event_bus import global_event_bus
        global_event_bus.emit_threadsafe({
            "type": "unread_count_updated",
            "session_id": session_id,
            "unread_count": 0
        })
        
    return {"status": "success", "session_id": session_id}

@router.get("/{session_id}/history")
def get_session_history(session_id: str, offset: int = 0, limit: int = 15, request: Request = None, user: User = Depends(get_current_user)):
    """
    Get paginated history for a session.
    offset: number of messages to skip from the END (e.g., offset=0 means last 'limit' messages)
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    session = orch.get_session_robust(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Timeline source of truth must be chat.json (not session.json context snapshot).
    history = orch.get_chat_history(session_id)
    total = len(history)
    
    # Calculate indices from the end
    end_idx = total - offset
    start_idx = max(0, end_idx - limit)
    
    if end_idx <= 0 or start_idx >= total:
        paginated = []
    else:
        paginated = history[start_idx:end_idx]
        
    return {
        "id": session_id,
        "history": paginated,
        "total": total,
        "has_more": start_idx > 0
    }

@router.post("/{session_id}/message")
def send_message(session_id: str, payload: dict, request: Request, user: User = Depends(get_current_user)):
    """
    Send a message as 'user' or 'operator'.
    """
    message = payload.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="Message required")

    attachments = payload.get("attachments", []) or []
    user_data = payload.get("user_data", {}) or {}
    if not isinstance(user_data, dict):
        user_data = {}
    user_data.setdefault("user_name", user.display_name or user.username)
        
    kernel = get_kernel(request)
    
    # We need a way to inject input into the Kernel for a specific session.
    # The Kernel.process_input method takes a 'driver_instance'.
    # We should use the ServerDriver instance.
    
    # Find ServerDriver
    server_driver = next((d for d in kernel.drivers if hasattr(d, 'app')), None)
    if not server_driver:
         # Fallback if we can't find it easily, but we are running INSIDE the server driver context practically
         # Actually, we can just pass 'None' as driver if we handle the response properly?
         # No, Kernel needs a driver to send response back to.
         raise HTTPException(status_code=500, detail="ServerDriver not found to route message")

    # Inject input
    # Note: process_input is async-ish (spawns thread).
    context = PrincipalContext(
        interface="web",
        sender_id=f"user_{user.id}",
        sender_name=user.display_name or user.username,
        session_id=session_id,
    )
    kernel.process_input(
        message,
        server_driver,
        user_id=session_id,
        user_data=user_data,
        context=context,
        attachments=attachments,
    )
    
    return {"status": "sent", "message": message}

@router.post("/{session_id}/inject")
def inject_system_message(session_id: str, payload: dict, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Inject a SYSTEM message or command. Admin only.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
        
    message = payload.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="Message required")

    kernel = get_kernel(request)
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Inject directly into history without triggering LLM immediately?
    # Or trigger LLM with system prompt?
    # Usually 'inject' means "Pretend the system said this" or "Add invisible instruction".
    
    session.add_message("system", message)
    # orch._save_session(session) # If accessible
    
    # Audit
    db.add(AuditLog(
        user_id=user.id,
        username=user.username,
        action="inject_message",
        target=session_id,
        details=json.dumps({"len": len(message)})
    ))
    db.commit()
    
    return {"status": "injected", "role": "system"}

@router.post("/{session_id}/profile_picture")
async def upload_profile_picture(
    session_id: str, 
    request: Request, 
    file: UploadFile = File(...), 
    user: User = Depends(get_current_user)
):
    """
    Upload a profile picture for a session.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    upload_dir = os.path.join(kernel.orchestrator.sessions_dir, session_id, "media", "profile_picture")
    os.makedirs(upload_dir, exist_ok=True)
    
    file_path = os.path.join(upload_dir, f"avatar_{file.filename}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    relative_path = f"media/profile_picture/avatar_{file.filename}"
    session.profile_picture = relative_path
    orch._save_session(session)
    
    from utils.event_bus import global_event_bus
    global_event_bus.emit_threadsafe({
        "type": "session_updated",
        "session_id": session.session_id,
        "profile_picture": session.profile_picture
    })
    
    return {
        "status": "success",
        "profile_picture": relative_path
    }

@router.post("/{session_id}/upload")
async def upload_files(
    session_id: str, 
    request: Request, 
    files: list[UploadFile] = File(...), 
    user: User = Depends(get_current_user)
):
    """
    Upload multiple files/images to a session (Max 10).
    """
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum of 10 files at a time.")

    kernel = get_kernel(request)
    orch = kernel.orchestrator
    session = orch.get_session_robust(session_id)
    
    if not session:
        # Auto-create if not found but message is being sent (Lazy Creation)
        interface = "web" # Default for API
        session = orch.create_session(session_id, interface)
        
    # Target directory: data/sessions/{session_id}/media/{file_type}
    # Standardized with AgentOrchestrator.standardize_attachments logic
    uploaded_info = []
    
    for file in files:
        # Determine type based on content type
        file_type = "file"
        if file.content_type and file.content_type.startswith("image/"): file_type = "image"
        elif file.content_type and file.content_type.startswith("video/"): file_type = "video"
        elif file.content_type and file.content_type.startswith("audio/"): file_type = "audio"
        
        target_dir = os.path.join(kernel.orchestrator.sessions_dir, session_id, "media", file_type)
        os.makedirs(target_dir, exist_ok=True)
        
        file_path = os.path.join(target_dir, file.filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_metadata = {
            "name": file.filename,
            "filename": file.filename,  # Backward-compatible alias
            "path": file_path,
            "type": file_type,
            "mime": file.content_type or "application/octet-stream"
        }
        uploaded_info.append(file_metadata)

    # Metadata is returned to the frontend, which will send a UNIFIED message 
    # via WebSocket/API containing both text and these attachments.
    # This prevents split messages and technical "Local: /path/..." text in the UI.
    
    return {
        "status": "uploaded",
        "count": len(files),
        "files": uploaded_info
    }
@router.delete("/{session_id}")
def delete_session(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Delete a session and all its associated data.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    orch.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}

@router.get("/{session_id}/media")
def get_session_media(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Returns media files and extracted links for a specific session.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    return orch.get_session_media(session_id)

@router.get("/{session_id}/events")
async def stream_session_events(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """
    Streams events for a specific session via SSE.
    """
    from utils.event_bus import global_event_bus
    import asyncio
    
    async def event_generator():
        queue = global_event_bus.subscribe()
        try:
            # Initial connection event
            yield f"data: {json.dumps({'type': 'connection', 'status': 'connected', 'session_id': session_id})}\n\n"
            
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    # Filter events by session_id if provided in event
                    # If event has session_id, it must match. If it doesn't, we send it anyway (global event)
                    if event.get("session_id") and event["session_id"] != session_id:
                        continue
                        
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            global_event_bus.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/{session_id}/playback")
def list_playback_runs(session_id: str, request: Request, user: User = Depends(get_current_user)):
    """Lists all playback runs for a session, with manifest summaries."""
    kernel = get_kernel(request)
    playback_dir = os.path.join(kernel.orchestrator.sessions_dir, session_id, "playback")
    
    if not os.path.isdir(playback_dir):
        return {"runs": []}
    
    runs = []
    for run_id in sorted(os.listdir(playback_dir), reverse=True):
        manifest_path = os.path.join(playback_dir, run_id, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            # Get first frame as thumbnail
            frames_dir = os.path.join(playback_dir, run_id, "frames")
            first_frame = None
            if os.path.isdir(frames_dir):
                frame_files = sorted(os.listdir(frames_dir))
                if frame_files:
                    first_frame = f"/api/sessions/{session_id}/playback/{run_id}/frames/{frame_files[0]}"
            
            runs.append({
                "run_id": run_id,
                "title": manifest.get("title", "Browser Session"),
                "status": manifest.get("status", "unknown"),
                "total_steps": len(manifest.get("steps", [])),
                "thumbnail": first_frame,
                "created_at": os.path.getmtime(manifest_path),
            })
        except Exception:
            continue
    
    return {"runs": runs}

@router.get("/{session_id}/playback/{run_id}/manifest")
def get_playback_manifest(session_id: str, run_id: str, request: Request, user: User = Depends(get_current_user)):
    """Returns the manifest for a specific playback run."""
    kernel = get_kernel(request)
    path = os.path.join(kernel.orchestrator.sessions_dir, session_id, "playback", run_id, "manifest.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Playback manifest not found")
    
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

@router.get("/{session_id}/playback/{run_id}/frames/{filename:path}")
def get_playback_frame(session_id: str, run_id: str, filename: str, request: Request, user: User = Depends(get_current_user)):
    """Returns a specific frame image for a playback run."""
    kernel = get_kernel(request)
    # Basic security: normalize path to prevent traversal
    filename = os.path.basename(filename)
    path = os.path.join(kernel.orchestrator.sessions_dir, session_id, "playback", run_id, "frames", filename)
    
    if not os.path.exists(path):
        # Playback viewers poll future frames; avoid noisy 404 spam for normal tailing.
        return Response(status_code=204)
        
    return FileResponse(path, media_type="image/jpeg")

@router.get("/{session_id}/files/{filename:path}")
def get_session_file(session_id: str, filename: str, request: Request, user: User = Depends(get_current_user)):
    """
    Securely serves a file from the session's workspace or uploads folder.
    """
    kernel = get_kernel(request)
    orch = kernel.orchestrator
    
    # Security: Prevent directory traversal
    filename = os.path.normpath(filename)
    if filename.startswith("..") or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Check search locations: 
    # 1. uploads/ (session specific)
    # 2. workspace/ (shared)
    
    locations = [
        os.path.join(orch.sessions_dir, session_id, "uploads", filename),
        os.path.join(orch.sessions_dir, session_id, filename), # Supports media/type/filename
        os.path.join(kernel.workspace_service.get_workspace_dir(), filename),
        os.path.join(kernel.workspace_service.output_dir, "exports", filename)
    ]
    
    for path in locations:
        if os.path.exists(path) and os.path.isfile(path):
             # Ensure the path is still within a safe root
             if any(path.startswith(os.path.abspath(r)) for r in [orch.sessions_dir, kernel.workspace_service.base_dir]):
                return FileResponse(path)
                
    raise HTTPException(status_code=404, detail=f"File {filename} not found in session {session_id}")
