from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SERVER_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ACTION_TOKEN_RE = re.compile(r"[^a-z0-9_]+")


class MCPTransportConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["http", "stdio"] = "http"
    endpoint: str = ""
    command: str = ""
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    headers: Dict[str, str] = Field(default_factory=dict)
    startup_timeout_s: float = 20.0


class MCPServerPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    trust_tier: Literal["trusted", "partner", "untrusted"] = "partner"
    namespace: str = "mcp"
    allow_tool_discovery: bool = True
    allow_resources: bool = False
    allow_prompts: bool = False
    default_requires_approval: Optional[bool] = None
    tool_allowlist: List[str] = Field(default_factory=list)
    tool_denylist: List[str] = Field(default_factory=list)

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            raise ValueError("namespace must be non-empty")
        if "." in normalized:
            raise ValueError("namespace must be a single token")
        return normalized


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    enabled: bool = True
    transport: MCPTransportConfig
    policy: MCPServerPolicy = Field(default_factory=MCPServerPolicy)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not _SERVER_ID_RE.fullmatch(normalized):
            raise ValueError("server id must match [a-z][a-z0-9_]*")
        return normalized

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("title must be non-empty")
        return text


class MCPToolAnnotations(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: Optional[str] = None
    readOnlyHint: Optional[bool] = None
    destructiveHint: Optional[bool] = None
    idempotentHint: Optional[bool] = None
    openWorldHint: Optional[bool] = None


class MCPToolDescriptor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    title: str = ""
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    annotations: MCPToolAnnotations = Field(default_factory=MCPToolAnnotations)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("tool name must be non-empty")
        return text

    @field_validator("input_schema")
    @classmethod
    def validate_schema(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        schema = dict(value or {})
        if not schema:
            return {"type": "object", "properties": {}, "additionalProperties": True}
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        return schema

    def normalized_title(self) -> str:
        if str(self.title or "").strip():
            return str(self.title).strip()
        return self.name.replace("_", " ").replace(".", " ").strip().title()


class MCPResourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uri: str
    name: str = ""
    title: str = ""
    description: str = ""
    mime_type: str = ""

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("resource uri must be non-empty")
        return text

    def normalized_title(self) -> str:
        if str(self.title or "").strip():
            return str(self.title).strip()
        if str(self.name or "").strip():
            return str(self.name).strip()
        return self.uri


class MCPPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allowed: bool
    reason: str
    risk_level: Literal["low", "medium", "high"]
    requires_approval: bool
    read_only: bool
    destructive: bool


class MCPActionDescriptor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action_id: str
    server_id: str
    tool_name: str
    title: str
    description: str
    parameters: Dict[str, Any]
    risk_level: Literal["low", "medium", "high"]
    requires_approval: bool
    read_only: bool
    metadata: Dict[str, Any] = Field(default_factory=dict)


def slugify_action_token(value: str) -> str:
    text = _ACTION_TOKEN_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return text or "tool"
