import json
import os
import re
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from utils.schema_utils import check_json_schema


NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)*$")
CONFIG_PATH_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")


class CapabilityMeta(BaseModel):
    id: str
    namespace: str
    version: str
    title: str
    description: str
    owner: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    visibility: Optional[str] = None

    @field_validator("id", "version", "title", "description")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must be non-empty")
        return text

    @field_validator("namespace")
    @classmethod
    def _valid_namespace(cls, value: str) -> str:
        ns = str(value or "").strip()
        if not NAMESPACE_RE.fullmatch(ns):
            raise ValueError("invalid namespace format")
        if "_" in ns:
            raise ValueError("namespace cannot contain underscores")
        return ns


class RuntimeMeta(BaseModel):
    module: str
    factory: str
    config_schema: Optional[str] = None

    @field_validator("module", "factory")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must be non-empty")
        return text


class AuthSecretPolicy(BaseModel):
    allow_create: bool = True
    allow_select: bool = True


class AuthSource(BaseModel):
    id: str
    type: Literal["oauth_account", "secret_ref", "strategy"]
    title: str
    description: str = ""
    provider: Optional[str] = None
    field_id: Optional[str] = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        token = str(value or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", token):
            raise ValueError("auth source id must be snake_case")
        return token


class AuthField(BaseModel):
    id: str
    type: Literal["secret_ref", "text", "username", "password", "client_id"]
    config_path: str
    required: bool = False
    title: str
    description: Optional[str] = None
    secret_policy: Optional[AuthSecretPolicy] = None

    @field_validator("id", "config_path", "title")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must be non-empty")
        return text

    @field_validator("id")
    @classmethod
    def _auth_id(cls, value: str) -> str:
        token = str(value or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", token):
            raise ValueError("auth field id must match [a-z][a-z0-9_]*")
        return token

    @field_validator("config_path")
    @classmethod
    def _auth_config_path(cls, value: str) -> str:
        path = str(value or "").strip()
        if not CONFIG_PATH_RE.fullmatch(path):
            raise ValueError("auth field config_path is invalid")
        return path

    @model_validator(mode="after")
    def _validate_secret_policy(self) -> "AuthField":
        if self.type == "secret_ref":
            self.secret_policy = self.secret_policy or AuthSecretPolicy()
        else:
            if self.secret_policy is not None:
                raise ValueError("secret_policy is allowed only for secret_ref fields")
        return self


class CapabilityAuth(BaseModel):
    mode: Literal[
        "none",
        "api_key",
        "oauth2",
        "basic",
        "bearer",
        "client_credentials",
        "custom",
        "hybrid",
    ]
    required: bool = False
    fields: List[AuthField] = Field(default_factory=list)
    oauth2: Optional[Dict[str, Any]] = None
    sources: List[AuthSource] = Field(default_factory=list)
    default_source: Optional[str] = None
    source_config_path: Optional[str] = None

    @model_validator(mode="after")
    def _validate_auth(self) -> "CapabilityAuth":
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
            return self

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

        ids = set()
        paths = set()
        for field in self.fields:
            if field.id in ids:
                raise ValueError(f"duplicate auth field id: {field.id}")
            ids.add(field.id)
            if field.config_path in paths:
                raise ValueError(f"duplicate auth field config_path: {field.config_path}")
            paths.add(field.config_path)

        source_ids = set()
        for source in self.sources:
            if source.id in source_ids:
                raise ValueError(f"duplicate auth source id: {source.id}")
            source_ids.add(source.id)
            if source.type == "secret_ref" and source.field_id and source.field_id not in ids:
                raise ValueError(f"auth source references unknown field_id: {source.field_id}")

        if self.default_source and self.default_source not in source_ids:
            raise ValueError("auth.default_source must reference an existing auth source")
        return self


class ActionPermissions(BaseModel):
    scopes: List[str]
    allow_anyone: bool
    requires_approval: bool

    @field_validator("scopes")
    @classmethod
    def _scopes_non_empty(cls, scopes: List[str]) -> List[str]:
        clean = [str(scope or "").strip() for scope in scopes or [] if str(scope or "").strip()]
        if not clean:
            raise ValueError("permissions.scopes must contain at least one scope")
        return clean


class CapabilityAction(BaseModel):
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
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must be non-empty")
        return text

    @field_validator("risk_level")
    @classmethod
    def _risk_level(cls, value: str) -> str:
        risk = str(value or "").strip().lower()
        if risk not in {"low", "medium", "high"}:
            raise ValueError("risk_level must be low|medium|high")
        return risk

    @field_validator("parameters")
    @classmethod
    def _json_schema(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("parameters must be a JSON Schema object")
        check_json_schema(value)
        return value

    @field_validator("result_schema")
    @classmethod
    def _result_json_schema(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("result_schema must be a JSON Schema object")
        check_json_schema(value)
        return value


class CapabilityContractV1(BaseModel):
    contract_version: str
    capability: CapabilityMeta
    runtime: RuntimeMeta
    auth: CapabilityAuth
    actions: List[CapabilityAction]
    policy_hints: Optional[Dict[str, Any]] = None

    @field_validator("contract_version")
    @classmethod
    def _contract_version(cls, value: str) -> str:
        version = str(value or "").strip()
        if version != "1.0":
            raise ValueError("contract_version must be '1.0'")
        return version

    @model_validator(mode="after")
    def _validate_actions(self) -> "CapabilityContractV1":
        seen: set[str] = set()
        ns = self.capability.namespace
        for action in self.actions:
            if action.id in seen:
                raise ValueError(f"duplicate action id: {action.id}")
            seen.add(action.id)
            if not action.id.startswith(f"{ns}."):
                raise ValueError(f"action id '{action.id}' outside namespace '{ns}'")
        return self


def load_contract_v1(contract_path: str) -> CapabilityContractV1:
    with open(contract_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return CapabilityContractV1.model_validate(raw)


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
