import json
import os
import re
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field, field_validator, ConfigDict
from utils.schema_utils import check_json_schema

NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)*$")
CONFIG_PATH_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")

class CapabilityAssets(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    icon_svg: str  # Mandatory vector format
    icon_16: Optional[str] = None
    icon_32: Optional[str] = None
    icon_64: Optional[str] = None

class CapabilityMeta(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    id: str
    namespace: str
    version: str
    title: str
    description: str
    owner: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    visibility: Optional[str] = None
    icon: Optional[str] = None
    assets: Optional[CapabilityAssets] = None

    @field_validator("id", "version", "title", "description")
    @classmethod
    def validate_non_empty(cls, v: str, info) -> str:
        if not str(v or "").strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return v

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        ns = str(v or "").strip()
        if not NAMESPACE_RE.fullmatch(ns):
            raise ValueError("invalid namespace format")
        if "_" in ns:
            raise ValueError("namespace cannot contain underscores")
        return ns

class RuntimeMeta(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    module: str
    factory: str
    config_schema: Optional[str] = None

    @field_validator("module", "factory")
    @classmethod
    def validate_non_empty(cls, v: str, info) -> str:
        if not str(v or "").strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return v

class AuthSecretPolicy(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    allow_create: bool = True
    allow_select: bool = True

class AuthSource(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    id: str
    type: str # Literal["oauth_account", "secret_ref", "strategy"]
    title: str
    description: str = ""
    provider: Optional[str] = None
    field_id: Optional[str] = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(v or "").strip()):
            raise ValueError("auth source id must be snake_case")
        return v

class AuthField(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    id: str
    type: str # Literal["secret_ref", "text", "username", "password", "client_id"]
    config_path: str
    title: str
    required: bool = False
    description: Optional[str] = None
    secret_policy: Optional[AuthSecretPolicy] = None

    @field_validator("id", "config_path", "title")
    @classmethod
    def validate_non_empty_fields(cls, v: str, info) -> str:
        if not str(v or "").strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return v

    @field_validator("id")
    @classmethod
    def validate_field_id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(v or "").strip()):
            raise ValueError("auth field id must match [a-z][a-z0-9_]*")
        return v

    @field_validator("config_path")
    @classmethod
    def validate_config_path(cls, v: str) -> str:
        if not CONFIG_PATH_RE.fullmatch(str(v or "").strip()):
            raise ValueError("auth field config_path is invalid")
        return v

    def model_post_init(self, __context: Any) -> None:
        if self.type == "secret_ref":
            if self.secret_policy is None:
                self.secret_policy = AuthSecretPolicy()
        else:
            if self.secret_policy is not None:
                raise ValueError("secret_policy is allowed only for secret_ref fields")

class CapabilityAuth(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    mode: str # Literal["none", "api_key", "oauth2", "basic", "bearer", "client_credentials", "custom", "hybrid"]
    required: bool = False
    fields: List[AuthField] = Field(default_factory=list)
    oauth2: Optional[Dict[str, Any]] = None
    sources: List[AuthSource] = Field(default_factory=list)
    default_source: Optional[str] = None
    source_config_path: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if self.mode == "none":
            if self.fields:
                raise ValueError("auth.fields must be empty when auth.mode is 'none'")
            if self.required:
                raise ValueError("auth.required must be false when auth.mode is 'none'")
            if self.oauth2 is not None:
                raise ValueError("auth.oauth2 is not allowed when auth.mode is 'none'")
            if self.sources:
                raise ValueError("auth.sources must be empty when auth.mode is 'none'")
            if self.default_source is not None:
                raise ValueError("auth.default_source must be absent when auth.mode is 'none'")
            if self.source_config_path is not None:
                raise ValueError("auth.source_config_path must be absent when auth.mode is 'none'")
            return

        if self.mode == "oauth2":
            if self.oauth2 is None:
                raise ValueError("auth.oauth2 is required when auth.mode is 'oauth2'")
        elif self.oauth2 is not None:
            raise ValueError("auth.oauth2 is allowed only when auth.mode is 'oauth2'")

        if self.mode == "hybrid":
            if not self.sources:
                raise ValueError("auth.sources is required when auth.mode is 'hybrid'")
            if not self.source_config_path:
                raise ValueError("auth.source_config_path is required when auth.mode is 'hybrid'")
        else:
            if self.sources:
                raise ValueError("auth.sources is allowed only when auth.mode is 'hybrid'")
            if self.default_source is not None:
                raise ValueError("auth.default_source is allowed only when auth.mode is 'hybrid'")
            if self.source_config_path is not None:
                raise ValueError("auth.source_config_path is allowed only when auth.mode is 'hybrid'")

        ids = {f.id for f in self.fields}
        paths = {f.config_path for f in self.fields}
        if len(ids) < len(self.fields):
            raise ValueError("duplicate auth field ids detected")
        if len(paths) < len(self.fields):
            raise ValueError("duplicate auth field config_paths detected")

        source_ids = {s.id for s in self.sources}
        if len(source_ids) < len(self.sources):
            raise ValueError("duplicate auth source ids detected")
            
        for source in self.sources:
            if source.type == "secret_ref" and source.field_id and source.field_id not in ids:
                raise ValueError(f"auth source references unknown field_id: {source.field_id}")

        if self.default_source and self.default_source not in source_ids:
            raise ValueError("auth.default_source must reference an existing auth source")

class ActionPermissions(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    scopes: List[str]
    allow_anyone: bool
    requires_approval: bool

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: List[str]) -> List[str]:
        cleaned = [str(s or "").strip() for s in v if str(s or "").strip()]
        if not cleaned:
            raise ValueError("permissions.scopes must contain at least one scope")
        return cleaned

class CapabilityAction(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    id: str
    title: str
    description: str
    handler: str
    risk_level: str
    permissions: ActionPermissions
    parameters: Dict[str, Any]
    result_schema: Optional[Dict[str, Any]] = None
    examples: List[Dict[str, Any]] = Field(default_factory=list)
    side_effect: Optional[str] = None

    @field_validator("id", "title", "description", "handler")
    @classmethod
    def validate_non_empty_action(cls, v: str, info) -> str:
        if not str(v or "").strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return v

    @field_validator("risk_level")
    @classmethod
    def validate_risk(cls, v: str) -> str:
        risk = str(v or "").strip().lower()
        if risk not in {"low", "medium", "high"}:
            raise ValueError("risk_level must be low|medium|high")
        return risk

    def model_post_init(self, __context: Any) -> None:
        if not isinstance(self.parameters, dict):
            raise ValueError("parameters must be a JSON Schema object")
        check_json_schema(self.parameters)
        
        if self.result_schema is not None:
            if not isinstance(self.result_schema, dict):
                raise ValueError("result_schema must be a JSON Schema object")
            check_json_schema(self.result_schema)


class CapabilityRetrievalFreshness(BaseModel):
    model_config = ConfigDict(extra='ignore')

    type: str = "live"
    sla_hours: Optional[int] = None


class CapabilityRetrievalQuality(BaseModel):
    model_config = ConfigDict(extra='ignore')

    default_confidence: Optional[float] = None
    trust_tier: Optional[str] = None
    citation_mode: Optional[str] = None


class CapabilityRetrievalCost(BaseModel):
    model_config = ConfigDict(extra='ignore')

    latency_class: Optional[str] = None
    quota_class: Optional[str] = None


class CapabilityRetrievalSetup(BaseModel):
    model_config = ConfigDict(extra='ignore')

    requires_auth: bool = False
    required_fields: List[str] = Field(default_factory=list)
    healthcheck_action: Optional[str] = None


class CapabilityRetrievalOutputContract(BaseModel):
    model_config = ConfigDict(extra='ignore')

    evidence_schema: Optional[str] = None
    entity_schema: Optional[str] = None


class CapabilityRetrievalProfile(BaseModel):
    model_config = ConfigDict(extra='ignore')

    enabled: bool = False
    roles: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    entity_types: List[str] = Field(default_factory=list)
    freshness: Optional[CapabilityRetrievalFreshness] = None
    quality: Optional[CapabilityRetrievalQuality] = None
    cost: Optional[CapabilityRetrievalCost] = None
    setup: Optional[CapabilityRetrievalSetup] = None
    output_contract: Optional[CapabilityRetrievalOutputContract] = None
    routing_hints: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("roles", "domains", "entity_types")
    @classmethod
    def _clean_string_lists(cls, v: List[str]) -> List[str]:
        seen: set[str] = set()
        out: List[str] = []
        for raw in v or []:
            value = str(raw or "").strip().lower()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out


class CapabilityDiscoverabilityProfile(BaseModel):
    model_config = ConfigDict(extra='ignore')

    enabled: bool = False
    roles: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    entity_types: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    routing_hints: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("roles", "domains", "entity_types", "keywords")
    @classmethod
    def _clean_string_lists(cls, v: List[str]) -> List[str]:
        seen: set[str] = set()
        out: List[str] = []
        for raw in v or []:
            value = str(raw or "").strip().lower()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out


class CapabilityContractV1(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    contract_version: str
    capability: CapabilityMeta
    runtime: RuntimeMeta
    auth: CapabilityAuth
    actions: List[CapabilityAction]
    retrieval_profile: Optional[CapabilityRetrievalProfile] = None
    discoverability_profile: Optional[CapabilityDiscoverabilityProfile] = None
    policy_hints: Optional[Dict[str, Any]] = None

    def model_post_init(self, __context: Any) -> None:
        if self.contract_version != "1.0":
            raise ValueError("contract_version must be '1.0'")
        
        seen = set()
        ns = self.capability.namespace
        for action in self.actions:
            if action.id in seen:
                raise ValueError(f"duplicate action id: {action.id}")
            seen.add(action.id)
            if not action.id.startswith(f"{ns}."):
                raise ValueError(f"action id '{action.id}' outside namespace '{ns}'")

def load_contract_v1(contract_path: str) -> CapabilityContractV1:
    with open(contract_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
        
    try:
        if hasattr(CapabilityContractV1, "model_validate"):
            return CapabilityContractV1.model_validate(raw)
    except Exception:
        pass
        
    return CapabilityContractV1(**raw)

def resolve_contract_config_schema_path(contract_path: str, contract: CapabilityContractV1) -> Optional[str]:
    schema_ref = str(contract.runtime.config_schema or "").strip()
    if not schema_ref:
        return None
    if os.path.isabs(schema_ref):
        return schema_ref
    return os.path.abspath(os.path.join(os.path.dirname(contract_path), schema_ref))

def load_contract_config_schema(contract_path: str, contract: CapabilityContractV1) -> Optional[Dict[str, Any]]:
    schema_path = resolve_contract_config_schema_path(contract_path, contract)
    if not schema_path:
        return None
    if not os.path.exists(schema_path):
        raise ValueError(f"config schema file not found: {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise ValueError("config schema must be a JSON object")
    check_json_schema(schema)
    return schema

def resolve_schema_node(schema: Dict[str, Any], config_path: str) -> Optional[Dict[str, Any]]:
    current: Optional[Dict[str, Any]] = schema
    for token in config_path.split("."):
        if not isinstance(current, dict):
            return None
        properties = current.get("properties")
        if not isinstance(properties, dict) or token not in properties:
            return None
        child = properties[token]
        if not isinstance(child, dict):
            return None
        current = child
    return current

def validate_auth_schema_alignment(
    contract: CapabilityContractV1,
    schema: Optional[Dict[str, Any]],
) -> List[str]:
    errors: List[str] = []
    auth = contract.auth
    if auth.mode == "none":
        return errors
    if schema is None:
        errors.append("auth metadata requires runtime.config_schema")
        return errors
    for field in auth.fields:
        node = resolve_schema_node(schema, field.config_path)
        if node is None:
            errors.append(f"auth field config_path not found in config schema: {field.config_path}")
            continue
        node_type = str(node.get("type") or "").strip()
        if field.type == "secret_ref" and node_type and node_type != "string":
            errors.append(f"secret_ref field must map to string config node: {field.config_path}")
        if field.type in {"text", "username", "password", "client_id"} and node_type and node_type != "string":
            errors.append(f"auth field must map to string config node: {field.config_path}")
    if auth.mode == "hybrid" and auth.source_config_path:
        source_node = resolve_schema_node(schema, auth.source_config_path)
        if source_node is None:
            errors.append(f"auth source_config_path not found in config schema: {auth.source_config_path}")
        else:
            source_node_type = str(source_node.get("type") or "").strip()
            if source_node_type and source_node_type != "string":
                errors.append(f"auth source_config_path must map to string config node: {auth.source_config_path}")
    return errors

def _get_config_value(config: Dict[str, Any], config_path: str) -> Any:
    current: Any = config
    for key in config_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current

def validate_auth_configuration(
    contract: CapabilityContractV1,
    config: Dict[str, Any],
    *,
    enabled: bool,
) -> List[str]:
    if not enabled:
        return []

    errors: List[str] = []
    auth = contract.auth
    if auth.mode == "none":
        return errors

    if auth.mode == "hybrid" and auth.source_config_path:
        raw_source = _get_config_value(config, auth.source_config_path)
        selected_source = str(raw_source or auth.default_source or "").strip()
        valid_sources = {source.id for source in auth.sources}
        if not selected_source:
            errors.append(f"missing auth source selection: {auth.source_config_path}")
        elif selected_source not in valid_sources:
            errors.append(f"invalid auth source '{selected_source}' for {auth.source_config_path}")

    for field in auth.fields:
        value = _get_config_value(config, field.config_path)
        text = str(value or "").strip() if value is not None else ""
        if field.required and not text:
            errors.append(f"missing required auth field: {field.config_path}")
            continue
        if field.type == "secret_ref" and text and not text.startswith("ENV_"):
            errors.append(f"auth field must reference vault key (ENV_*): {field.config_path}")

    if auth.required and not auth.fields:
        errors.append("auth.required is true but auth.fields is empty")
    return errors
