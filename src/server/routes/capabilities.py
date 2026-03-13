import json
import os
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from capabilities.contract_v1 import (
    CapabilityContractV1,
    load_contract_v1,
    load_contract_config_schema,
    resolve_contract_config_schema_path,
    validate_auth_schema_alignment,
    validate_auth_configuration,
)
from core.identity import PrincipalContext
from utils.schema_utils import ValidationError, validate_json_instance
from ..auth import get_current_user
from ..core.database import get_db
from ..core.models import AuditLog, User

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])
logger = logging.getLogger("CapabilityRoutes")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAPABILITIES_DIR = os.path.join(BASE_DIR, "capabilities")


def _load_config_schema(contract_path: str) -> Dict[str, Any]:
    contract = load_contract_v1(contract_path)
    schema = load_contract_config_schema(contract_path, contract)
    auth_schema_errors = validate_auth_schema_alignment(contract, schema)
    if auth_schema_errors:
        raise ValueError("; ".join(auth_schema_errors))
    return schema or {}


def _mask_config(config: Dict[str, Any], auth: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(config, dict):
        return config
    masked = json.loads(json.dumps(config))
    fields = auth.get("fields", []) if isinstance(auth, dict) else []
    for field in fields:
        if not isinstance(field, dict) or field.get("type") != "secret_ref":
            continue
        path = str(field.get("config_path", "")).strip()
        if not path:
            continue
        tokens = path.split(".")
        cursor = masked
        for token in tokens[:-1]:
            if not isinstance(cursor, dict) or token not in cursor:
                cursor = None
                break
            cursor = cursor[token]
        if isinstance(cursor, dict) and tokens[-1] in cursor:
            current_value = cursor[tokens[-1]]
            text = str(current_value or "").strip()
            # secret_ref fields should expose the vault reference (ENV_*) to the UI,
            # while still masking any accidental raw secret value.
            if text and text.startswith("ENV_"):
                continue
            cursor[tokens[-1]] = "********"
    return masked


def _set_config_value(config: Dict[str, Any], config_path: str, value: Any) -> None:
    current = config
    tokens = [token for token in str(config_path or "").split(".") if token]
    if not tokens:
        return
    for token in tokens[:-1]:
        next_value = current.get(token)
        if not isinstance(next_value, dict):
            next_value = {}
            current[token] = next_value
        current = next_value
    current[tokens[-1]] = value


def _get_config_value(config: Dict[str, Any], config_path: str) -> Any:
    current: Any = config
    for key in str(config_path or "").split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _merge_patch_preserving_masked(current: Any, patch: Any) -> Any:
    if patch == "********":
        return current
    if isinstance(current, dict) and isinstance(patch, dict):
        merged = dict(current)
        for key, value in patch.items():
            merged[key] = _merge_patch_preserving_masked(merged.get(key), value)
        return merged
    return patch


def _normalize_auth_config_refs(config: Dict[str, Any], contract: CapabilityContractV1) -> Dict[str, Any]:
    for field in contract.auth.fields:
        if field.type != "secret_ref":
            continue
        raw_value = _get_config_value(config, field.config_path)
        text = str(raw_value or "").strip()
        if not text or text == "********":
            continue
        normalized = text if text.startswith("ENV_") else f"ENV_{text}"
        if normalized != text:
            _set_config_value(config, field.config_path, normalized)
    return config


def _validate_config(
    config: Dict[str, Any],
    schema: Dict[str, Any],
    enabled: bool,
    *,
    contract: Any = None,
) -> tuple[List[str], List[str]]:
    errors: List[str] = []
    missing: List[str] = []
    if not schema:
        if contract is not None:
            errors.extend(validate_auth_configuration(contract, config, enabled=enabled))
        return errors, missing
    # Keep UI/API behavior aligned with runtime loader:
    # required config is enforced only when capability is enabled.
    if not enabled:
        return errors, missing
    try:
        validate_json_instance(config, schema)
    except ValidationError as exc:
        message = str(exc)
        errors.append(message)
    if contract is not None:
        errors.extend(validate_auth_configuration(contract, config, enabled=enabled))
    return errors, missing


@router.get("/")
def list_capabilities(request: Request, user: User = Depends(get_current_user)):
    kernel = getattr(request.app.state, "kernel", None)
    config_manager = getattr(kernel, "config_manager", None) if kernel else None
    raw_config: Dict[str, Any] = {}
    if config_manager and getattr(config_manager, "config_file", None):
        try:
            if os.path.exists(config_manager.config_file):
                with open(config_manager.config_file, "r", encoding="utf-8") as handle:
                    raw_config = json.load(handle) or {}
        except Exception:
            raw_config = {}
    capabilities_config = raw_config.get("capabilities", {}) if isinstance(raw_config, dict) else {}

    rows: List[Dict[str, Any]] = []
    if not os.path.exists(CAPABILITIES_DIR):
        return rows

    for item in sorted(os.listdir(CAPABILITIES_DIR)):
        folder = os.path.join(CAPABILITIES_DIR, item)
        if not os.path.isdir(folder) or item.startswith("__") or item == "shared":
            continue
        contract_path = os.path.join(folder, "contract.json")
        if not os.path.exists(contract_path):
            continue
        capability_cfg = dict(capabilities_config.get(item, {}) or {})
        enabled = bool(capability_cfg.get("enabled", False))
        try:
            contract = load_contract_v1(contract_path)
            schema = _load_config_schema(contract_path)
            errors, missing = _validate_config(
                capability_cfg,
                schema,
                enabled=enabled,
                contract=contract,
            )
            rows.append(
                {
                    "id": contract.capability.id,
                    "namespace": contract.capability.namespace,
                    "version": contract.capability.version,
                    "name": contract.capability.title,
                    "title": contract.capability.title,
                    "description": contract.capability.description,
                    "owner": contract.capability.owner,
                    "tags": list(contract.capability.tags),
                    "visibility": contract.capability.visibility,
                    "auth": contract.auth.model_dump(),
                    "actions": [action.id for action in contract.actions],
                    "enabled": enabled,
                    "config": _mask_config(capability_cfg, contract.auth.model_dump()),
                    "config_schema": schema,
                    "validation_errors": errors,
                    "missing_required": missing,
                    "load_status": "valid",
                    "icon_key": "",
                    "icon_url": "",
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "id": item,
                    "namespace": "",
                    "version": "",
                    "name": item,
                    "title": item,
                    "description": "",
                    "owner": None,
                    "tags": [],
                    "visibility": None,
                    "auth": {"mode": "none", "required": False, "fields": []},
                    "actions": [],
                    "enabled": enabled,
                    "config": _mask_config(capability_cfg, {"fields": []}),
                    "config_schema": {},
                    "validation_errors": [str(exc)],
                    "missing_required": [],
                    "load_status": "invalid_contract",
                    "icon_key": "",
                    "icon_url": "",
                }
            )
    return rows


@router.patch("/{capability_id}/config")
def update_capability_config(
    capability_id: str,
    patch_data: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can configure capabilities")

    kernel = getattr(request.app.state, "kernel", None)
    config_manager = getattr(kernel, "config_manager", None) if kernel else None
    if not config_manager:
        raise HTTPException(status_code=500, detail="Config manager not available")

    contract_path = os.path.join(CAPABILITIES_DIR, capability_id, "contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=404, detail=f"Capability '{capability_id}' not found")

    try:
        contract = load_contract_v1(contract_path)
        schema = _load_config_schema(contract_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid capability contract: {exc}")

    raw_config: Dict[str, Any] = {}
    try:
        if os.path.exists(config_manager.config_file):
            with open(config_manager.config_file, "r", encoding="utf-8") as handle:
                raw_config = json.load(handle) or {}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read raw config: {exc}")

    raw_capabilities = raw_config.get("capabilities", {})
    capability_config = dict(raw_capabilities.get(capability_id, {}) or {})
    logger.info(
        "patch_capability_config.request | capability=%s payload=%s existing=%s",
        capability_id,
        json.dumps(patch_data, ensure_ascii=False, default=str),
        json.dumps(_mask_config(capability_config, contract.auth.model_dump()), ensure_ascii=False, default=str),
    )
    capability_config = _merge_patch_preserving_masked(capability_config, patch_data)
    capability_config = _normalize_auth_config_refs(capability_config, contract)
    logger.info(
        "patch_capability_config.merged | capability=%s merged=%s",
        capability_id,
        json.dumps(_mask_config(capability_config, contract.auth.model_dump()), ensure_ascii=False, default=str),
    )

    enabled = bool(capability_config.get("enabled", False))
    errors, missing = _validate_config(
        capability_config,
        schema,
        enabled=enabled,
        contract=contract,
    )
    if errors:
        logger.error(
            "patch_capability_config.validation_failed | capability=%s enabled=%s errors=%s missing=%s",
            capability_id,
            enabled,
            json.dumps(errors, ensure_ascii=False, default=str),
            json.dumps(missing, ensure_ascii=False, default=str),
        )
        raise HTTPException(status_code=400, detail={"errors": errors, "missing": missing})

    raw_config.setdefault("capabilities", {})
    raw_config["capabilities"][capability_id] = capability_config
    try:
        with open(config_manager.config_file, "w", encoding="utf-8") as handle:
            json.dump(raw_config, handle, indent=4)
        config_manager.load()
    except Exception as exc:
        logger.exception("patch_capability_config.save_failed | capability=%s", capability_id)
        raise HTTPException(status_code=500, detail=f"Failed to save config: {exc}")

    payload_preview = {
        key: "***" if "key" in key.lower() or "secret" in key.lower() else value
        for key, value in patch_data.items()
    }
    db.add(
        AuditLog(
            user_id=user.id,
            username=user.username,
            action="patch_capability_config",
            target=capability_id,
            details=json.dumps(payload_preview),
        )
    )
    db.commit()
    logger.info("patch_capability_config.success | capability=%s", capability_id)

    return {
        "status": "updated",
        "config": _mask_config(capability_config, contract.auth.model_dump()),
        "validation_errors": errors,
        "missing_required": missing,
    }


@router.post("/{capability_id}/toggle")
def toggle_capability(
    capability_id: str,
    enable: bool,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_capability_config(capability_id, {"enabled": enable}, request, user, db)


@router.get("/registry")
def get_capability_registry(
    request: Request,
    interface: str | None = None,
    sender_id: str | None = None,
    session_id: str | None = None,
    chat_id: str | None = None,
    is_group: bool = False,
    user: User = Depends(get_current_user),
):
    kernel = getattr(request.app.state, "kernel", None)
    if not kernel:
        raise HTTPException(status_code=500, detail="Kernel not available")

    registry = kernel.capability_registry
    allowed_actions_set = None
    if any(v is not None for v in [interface, sender_id, session_id, chat_id]) or is_group:
        if not interface or not sender_id:
            raise HTTPException(status_code=400, detail="interface and sender_id are required for principal-scoped registry")
        orchestrator = getattr(kernel, "orchestrator", None)
        access_controller = getattr(orchestrator, "access_controller", None) if orchestrator else None
        if not access_controller:
            raise HTTPException(status_code=500, detail="Access controller not available")
        context = PrincipalContext(
            interface=interface,
            sender_id=sender_id,
            sender_name=getattr(user, "username", None),
            chat_id=chat_id if is_group else None,
            is_group=is_group,
            session_id=session_id or f"{interface}:{sender_id}",
        )
        allowed_actions = access_controller.get_allowed_actions(
            context,
            registry,
            getattr(kernel, "config_manager", None),
        )
        allowed_actions_set = set(allowed_actions)

    rows: List[Dict[str, Any]] = []
    for action_id in sorted(registry.action_map.keys()):
        if allowed_actions_set is not None and action_id not in allowed_actions_set:
            continue
        metadata = registry.get_action_metadata(action_id)
        if not metadata:
            raise HTTPException(status_code=500, detail=f"Canonical metadata missing for action '{action_id}'")
        capability = registry.get_capability_for_action(action_id)
        rows.append(
            {
                "id": action_id,
                "capability_name": capability.name if capability else metadata.get("capability_id", ""),
                "namespace": metadata.get("namespace", ""),
                "description": metadata.get("description", ""),
                "risk_level": metadata.get("risk_level", ""),
                "permissions": metadata.get("permissions", {}),
                "icon_key": "",
                "icon_url": "",
            }
        )
    return rows
