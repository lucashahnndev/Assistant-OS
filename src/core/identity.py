from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
import time

class AccessStatus(str, Enum):
    APPROVED = "approved"
    PENDING = "pending"
    BLOCKED = "blocked"

class AccessMode(str, Enum):
    APPROVED_ONLY = "approved_only"
    ANYONE = "anyone"
    AUTO_APPROVE = "auto_approve"

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class PrincipalContext(BaseModel):
    interface: str  # "telegram", "whatsapp", "discord", "web", etc.
    sender_id: str
    sender_name: Optional[str] = None
    chat_id: Optional[str] = None
    chat_name: Optional[str] = None
    is_group: bool = False
    roles: List[str] = Field(default_factory=list)
    session_id: str
    message_id: Optional[str] = None

class EntityOverrides(BaseModel):
    allow_capabilities: List[str] = Field(default_factory=list)
    deny_capabilities: List[str] = Field(default_factory=list)
    allow_actions: List[str] = Field(default_factory=list)
    deny_actions: List[str] = Field(default_factory=list)

class PermissionGroup(BaseModel):
    id: str
    name: str
    description: str = ""
    allow_capabilities: List[str] = Field(default_factory=list)
    deny_capabilities: List[str] = Field(default_factory=list)
    allow_actions: List[str] = Field(default_factory=list)
    deny_actions: List[str] = Field(default_factory=list)
    worker_view_scope: str = "owner_identity"   # self_session | owner_session | owner_identity | global
    worker_control_scope: str = "owner_identity" # self_session | owner_session | owner_identity | global
    is_system: bool = False

class UserEntity(BaseModel):
    id: str
    interface: str
    status: AccessStatus = AccessStatus.PENDING
    group_id: Optional[str] = None
    display_name: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    first_seen_at: float = Field(default_factory=time.time)
    last_seen_at: float = Field(default_factory=time.time)
    overrides: EntityOverrides = Field(default_factory=EntityOverrides)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ChatEntity(BaseModel):
    id: str
    interface: str
    status: AccessStatus = AccessStatus.PENDING
    group_id: Optional[str] = None
    title: Optional[str] = None
    first_seen_at: float = Field(default_factory=time.time)
    last_seen_at: float = Field(default_factory=time.time)
    overrides: EntityOverrides = Field(default_factory=EntityOverrides)
    metadata: Dict[str, Any] = Field(default_factory=dict)
