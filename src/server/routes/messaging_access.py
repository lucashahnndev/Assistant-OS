from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from core.identity import AccessStatus, EntityOverrides, PermissionGroup
from ..auth import get_current_user, require_admin_user
from ..core.models import User

router = APIRouter(prefix="/api/messaging_access", tags=["messaging_access"])

class InterfaceUpdate(BaseModel):
    dm_mode: Optional[str] = None
    group_mode: Optional[str] = None
    default_user_group: Optional[str] = None
    default_chat_group: Optional[str] = None
    auto_approve_user_group: Optional[str] = None
    auto_approve_chat_group: Optional[str] = None
    allow_anyone_in_chats: Optional[List[str]] = None
    rate_limit_enabled: Optional[bool] = None
    max_msgs_per_min: Optional[int] = None
    approval_decisions: Optional[Dict[str, Any]] = None

class StatusUpdate(BaseModel):
    status: AccessStatus

class GroupAssignUpdate(BaseModel):
    group_id: str

class GroupCreateRequest(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    allow_capabilities: List[str] = Field(default_factory=list)
    deny_capabilities: List[str] = Field(default_factory=list)
    allow_actions: List[str] = Field(default_factory=list)
    deny_actions: List[str] = Field(default_factory=list)
    worker_view_scope: str = "owner_identity"
    worker_control_scope: str = "owner_identity"

class GroupPatchRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    allow_capabilities: Optional[List[str]] = None
    deny_capabilities: Optional[List[str]] = None
    allow_actions: Optional[List[str]] = None
    deny_actions: Optional[List[str]] = None
    worker_view_scope: Optional[str] = None
    worker_control_scope: Optional[str] = None

@router.get("/interfaces")
async def get_interfaces(request: Request, user: User = Depends(get_current_user)):
    kernel = request.app.state.kernel
    return kernel.orchestrator.access_controller.identity_service.policy.get("interfaces", {})

@router.patch("/interfaces/{interface}")
async def update_interface(interface: str, update: InterfaceUpdate, request: Request, user: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    
    if interface not in service.policy["interfaces"]:
        service.policy["interfaces"][interface] = {
            "dm_mode": "approved_only",
            "group_mode": "approved_only",
            "default_user_group": "medium",
            "default_chat_group": "medium",
            "auto_approve_user_group": "medium",
            "auto_approve_chat_group": "medium",
            "allow_anyone_in_chats": [],
            "rate_limit_enabled": True,
            "max_msgs_per_min": 10,
            "approval_decisions": {
                "enabled": True,
                "allowed_groups": ["master"],
                "denied_groups": [],
            },
        }
    
    current = service.policy["interfaces"][interface]
    updates = update.model_dump(exclude_unset=True)
    group_fields = {
        "default_user_group",
        "default_chat_group",
        "auto_approve_user_group",
        "auto_approve_chat_group",
    }
    for field, value in updates.items():
        if field == "approval_decisions":
            approval_payload = value if isinstance(value, dict) else {}
            current_approval = current.get("approval_decisions")
            if not isinstance(current_approval, dict):
                current_approval = {}
            merged_approval = dict(current_approval)
            merged_approval.update(approval_payload)

            for list_key in ("allowed_groups", "denied_groups"):
                raw_list = merged_approval.get(list_key)
                if raw_list is None:
                    raw_list = []
                if not isinstance(raw_list, list):
                    raise HTTPException(status_code=400, detail=f"Field '{list_key}' must be a list")
                normalized = []
                for item in raw_list:
                    token = str(item or "").strip().lower()
                    if not token:
                        continue
                    if token in {"*", "all"}:
                        token = "*"
                    else:
                        resolved_group = service.resolve_permission_group_id(token)
                        if not resolved_group:
                            raise HTTPException(status_code=400, detail=f"Permission group '{token}' not found")
                        token = resolved_group
                    if token not in normalized:
                        normalized.append(token)
                merged_approval[list_key] = normalized
            merged_approval["enabled"] = bool(merged_approval.get("enabled", True))
            current["approval_decisions"] = merged_approval
            continue
        if field in group_fields and value:
            resolved_group = service.resolve_permission_group_id(value)
            if not resolved_group:
                raise HTTPException(status_code=400, detail=f"Permission group '{value}' not found")
            current[field] = resolved_group
            continue
        current[field] = value
        
    service.save_policy()
    return current

@router.get("/users")
async def list_users(request: Request, interface: Optional[str] = None, status: Optional[str] = None, user: User = Depends(get_current_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    return service.list_entities("users", interface=interface, status=status)

@router.post("/users/{interface}/{user_id}/group")
async def update_user_group(interface: str, user_id: str, update: GroupAssignUpdate, request: Request, user_ctx: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    entity = service.get_user(interface, user_id)
    if not entity:
        raise HTTPException(status_code=404, detail="User not found")
    resolved_group = service.resolve_permission_group_id(update.group_id)
    if not resolved_group:
        raise HTTPException(status_code=400, detail="Permission group not found")

    entity.group_id = resolved_group
    service.save_user(entity)
    return entity

@router.post("/users/{interface}/{user_id}/status")
async def update_user_status(interface: str, user_id: str, update: StatusUpdate, request: Request, user_ctx: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    user = service.get_user(interface, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.status = update.status
    service.save_user(user)
    return user

@router.patch("/users/{interface}/{user_id}/overrides")
async def update_user_overrides(interface: str, user_id: str, overrides: EntityOverrides, request: Request, user_ctx: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    user = service.get_user(interface, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.overrides = overrides
    service.save_user(user)
    return user

@router.get("/chats")
async def list_chats(request: Request, interface: Optional[str] = None, status: Optional[str] = None, user: User = Depends(get_current_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    return service.list_entities("chats", interface=interface, status=status)

@router.post("/chats/{interface}/{chat_id}/group")
async def update_chat_group(interface: str, chat_id: str, update: GroupAssignUpdate, request: Request, user_ctx: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    entity = service.get_chat(interface, chat_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Chat not found")
    resolved_group = service.resolve_permission_group_id(update.group_id)
    if not resolved_group:
        raise HTTPException(status_code=400, detail="Permission group not found")

    entity.group_id = resolved_group
    service.save_chat(entity)
    return entity

@router.post("/chats/{interface}/{chat_id}/status")
async def update_chat_status(interface: str, chat_id: str, update: StatusUpdate, request: Request, user_ctx: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    chat = service.get_chat(interface, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    chat.status = update.status
    service.save_chat(chat)
    return chat

@router.patch("/chats/{interface}/{chat_id}/overrides")
async def update_chat_overrides(interface: str, chat_id: str, overrides: EntityOverrides, request: Request, user_ctx: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    chat = service.get_chat(interface, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    chat.overrides = overrides
    service.save_chat(chat)
    return chat

@router.get("/groups")
async def list_groups(request: Request, user: User = Depends(get_current_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    return service.list_permission_groups()

@router.get("/approval-audit")
async def get_approval_audit(
    request: Request,
    interface: Optional[str] = None,
    limit: int = 200,
    command: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    kernel = request.app.state.kernel
    scheduler = kernel.scheduler
    command_filter = str(command or "").strip().lower()
    if command_filter and command_filter not in {"approve", "deny"}:
        raise HTTPException(status_code=400, detail="Invalid command filter. Use 'approve' or 'deny'.")
    interface_filter = str(interface or "").strip().lower()

    def _infer_interface_from_session_id(session_id: str) -> str:
        sid = str(session_id or "").strip().lower()
        if sid.startswith("telegram_"):
            return "telegram"
        if sid.startswith("voice"):
            return "voice"
        if sid.startswith("whatsapp_") or sid.startswith("wa_"):
            return "whatsapp"
        return "web" if sid else "unknown"

    safe_limit = max(1, min(int(limit or 200), 1000))
    works = scheduler.list_works(include_completed=True, limit=500, include_context=False)
    records: List[Dict[str, Any]] = []
    for work in works:
        work_id = str(work.get("work_id") or "").strip()
        if not work_id:
            continue
        events = scheduler.read_work_events(work_id, limit=400)
        for event in events:
            if str(event.get("event") or "").strip().lower() != "work_command":
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            cmd = str(payload.get("command") or "").strip().lower()
            if cmd not in {"approve", "deny"}:
                continue
            if command_filter and cmd != command_filter:
                continue
            source_session_id = str(payload.get("source_session_id") or "").strip()
            source_interface = _infer_interface_from_session_id(source_session_id)
            if interface_filter and source_interface != interface_filter:
                continue
            records.append(
                {
                    "ts": event.get("ts"),
                    "command": cmd,
                    "work_id": work_id,
                    "work_status": work.get("status"),
                    "work_label": work.get("label"),
                    "work_key": work.get("key"),
                    "target_session_id": work.get("session_id"),
                    "owner_session_id": work.get("owner_session_id"),
                    "owner_sender_id": work.get("owner_sender_id"),
                    "source_session_id": source_session_id,
                    "source_interface": source_interface,
                }
            )
    records.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return {"items": records[:safe_limit], "count": min(len(records), safe_limit)}

@router.post("/groups")
async def create_group(payload: GroupCreateRequest, request: Request, user_ctx: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    group_id = payload.id.strip().lower().replace(" ", "_")
    if not group_id:
        raise HTTPException(status_code=400, detail="Group id cannot be empty")
    if service.get_permission_group(group_id):
        raise HTTPException(status_code=409, detail="Group id already exists")

    group = PermissionGroup(
        id=group_id,
        name=payload.name.strip(),
        description=(payload.description or "").strip(),
        allow_capabilities=payload.allow_capabilities,
        deny_capabilities=payload.deny_capabilities,
        allow_actions=payload.allow_actions,
        deny_actions=payload.deny_actions,
        worker_view_scope=payload.worker_view_scope,
        worker_control_scope=payload.worker_control_scope,
        is_system=False,
    )
    service.save_permission_group(group)
    return group

@router.patch("/groups/{group_id}")
async def patch_group(group_id: str, payload: GroupPatchRequest, request: Request, user_ctx: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    resolved_group_id = service.resolve_permission_group_id(group_id)
    existing = service.get_permission_group(resolved_group_id or group_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Group not found")

    patch_data = payload.model_dump(exclude_unset=True)
    group_data = existing.model_dump()
    group_data.update(patch_data)

    # Keep immutable identity
    group_data["id"] = existing.id
    if existing.is_system:
        group_data["is_system"] = True

    updated = PermissionGroup(**group_data)
    service.save_permission_group(updated)
    return updated

@router.delete("/groups/{group_id}")
async def delete_group(group_id: str, request: Request, user_ctx: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    resolved_group_id = service.resolve_permission_group_id(group_id) or group_id
    try:
        deleted = service.delete_permission_group(resolved_group_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"status": "deleted", "group_id": resolved_group_id}
