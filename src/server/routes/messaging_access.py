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

class StatusUpdate(BaseModel):
    status: AccessStatus

class GroupAssignUpdate(BaseModel):
    group_id: str

class GroupCreateRequest(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    allow_skills: List[str] = Field(default_factory=list)
    deny_skills: List[str] = Field(default_factory=list)
    allow_actions: List[str] = Field(default_factory=list)
    deny_actions: List[str] = Field(default_factory=list)

class GroupPatchRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    allow_skills: Optional[List[str]] = None
    deny_skills: Optional[List[str]] = None
    allow_actions: Optional[List[str]] = None
    deny_actions: Optional[List[str]] = None

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
            "max_msgs_per_min": 10
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
        if field in group_fields and value:
            if not service.get_permission_group(value):
                raise HTTPException(status_code=400, detail=f"Permission group '{value}' not found")
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
    if not service.get_permission_group(update.group_id):
        raise HTTPException(status_code=400, detail="Permission group not found")

    entity.group_id = update.group_id
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
    if not service.get_permission_group(update.group_id):
        raise HTTPException(status_code=400, detail="Permission group not found")

    entity.group_id = update.group_id
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
        allow_skills=payload.allow_skills,
        deny_skills=payload.deny_skills,
        allow_actions=payload.allow_actions,
        deny_actions=payload.deny_actions,
        is_system=False,
    )
    service.save_permission_group(group)
    return group

@router.patch("/groups/{group_id}")
async def patch_group(group_id: str, payload: GroupPatchRequest, request: Request, user_ctx: User = Depends(require_admin_user)):
    kernel = request.app.state.kernel
    service = kernel.orchestrator.access_controller.identity_service
    existing = service.get_permission_group(group_id)
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
    try:
        deleted = service.delete_permission_group(group_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"status": "deleted", "group_id": group_id}
