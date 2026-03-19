import json
import os
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
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
    registry = getattr(kernel, "capability_registry", None) if kernel else None
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
    research_cfg = capabilities_config.get("research_retrieve", {}) if isinstance(capabilities_config, dict) else {}
    defaults_cfg = research_cfg.get("defaults", {}) if isinstance(research_cfg, dict) else {}
    control_plane_cfg = defaults_cfg.get("control_plane", {}) if isinstance(defaults_cfg, dict) else {}
    control_plane_overrides = control_plane_cfg.get("overrides") if isinstance(control_plane_cfg.get("overrides"), dict) else {}
    control_plane_scorecard = control_plane_cfg.get("scorecard") if isinstance(control_plane_cfg.get("scorecard"), dict) else {}
    runtime_offer_by_id: Dict[str, Dict[str, Any]] = {}
    if registry and hasattr(registry, "list_retrieval_offers"):
        try:
            offers = registry.list_retrieval_offers()
            runtime_offer_by_id = {
                str(row.get("capability_id") or ""): row
                for row in offers
                if isinstance(row, dict) and str(row.get("capability_id") or "").strip()
            }
        except Exception:
            runtime_offer_by_id = {}

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
                    "retrieval_profile": contract.retrieval_profile.model_dump() if contract.retrieval_profile else None,
                    "retrieval_runtime": _merged_retrieval_runtime(
                        capability_id=contract.capability.id,
                        runtime_offer_by_id=runtime_offer_by_id,
                        control_plane_overrides=control_plane_overrides,
                        control_plane_scorecard=control_plane_scorecard,
                    ),
                    "enabled": enabled,
                    "config": _mask_config(capability_cfg, contract.auth.model_dump()),
                    "config_schema": schema,
                    "validation_errors": errors,
                    "missing_required": missing,
                    "icon_url": f"/api/capabilities/{contract.capability.id}/icon/svg",
                    "assets": contract.capability.assets.model_dump(),
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
                    "retrieval_profile": None,
                    "enabled": enabled,
                    "config": _mask_config(capability_cfg, {"fields": []}),
                    "config_schema": {},
                    "validation_errors": [str(exc)],
                    "missing_required": [],
                    "icon_url": "",
                    "assets": None,
                }
            )
    return rows


def _merged_retrieval_runtime(
    *,
    capability_id: str,
    runtime_offer_by_id: Dict[str, Dict[str, Any]],
    control_plane_overrides: Dict[str, Any],
    control_plane_scorecard: Dict[str, Any],
) -> Dict[str, Any]:
    offer = runtime_offer_by_id.get(capability_id, {})
    row = dict(offer) if isinstance(offer, dict) else {}
    override = control_plane_overrides.get(capability_id) if isinstance(control_plane_overrides.get(capability_id), dict) else {}
    scorecard = control_plane_scorecard.get(capability_id) if isinstance(control_plane_scorecard.get(capability_id), dict) else {}
    if override:
        row.update(override)
    if scorecard:
        row.update(scorecard)

    if not row:
        return {}

    if bool(row.get("disabled")):
        state = "disabled"
    elif bool(row.get("quota_exceeded")):
        state = "quota_exceeded"
    elif bool(row.get("error_previous")):
        state = "error_previous"
    elif bool(row.get("degraded")):
        state = "degraded"
    elif row.get("setup_ready") is False:
        state = "setup_pending"
    else:
        state = "ready"
    row["operational_state"] = state
    return row


@router.get("/retrieval/offers")
def list_retrieval_offers(
    request: Request,
    intent: str | None = None,
    domain: str | None = None,
    role: str | None = None,
    entity_type: str | None = None,
    user: User = Depends(get_current_user),
):
    _ = user
    kernel = getattr(request.app.state, "kernel", None)
    registry = getattr(kernel, "capability_registry", None) if kernel else None
    if not registry or not hasattr(registry, "list_retrieval_offers"):
        raise HTTPException(status_code=500, detail="Capability registry retrieval offers unavailable")

    rows = registry.list_retrieval_offers(
        intent=intent,
        domain=domain,
        role=role,
        entity_type=entity_type,
    )
    return {"count": len(rows), "offers": rows}


@router.get("/retrieval/control-plane")
def get_retrieval_control_plane(request: Request, user: User = Depends(get_current_user)):
    _ = user
    kernel = getattr(request.app.state, "kernel", None)
    config_manager = getattr(kernel, "config_manager", None) if kernel else None
    if not config_manager:
        raise HTTPException(status_code=500, detail="Config manager not available")

    raw_config: Dict[str, Any] = {}
    try:
        if os.path.exists(config_manager.config_file):
            with open(config_manager.config_file, "r", encoding="utf-8") as handle:
                raw_config = json.load(handle) or {}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read raw config: {exc}")

    caps = raw_config.get("capabilities", {}) if isinstance(raw_config, dict) else {}
    research_cfg = caps.get("research_retrieve", {}) if isinstance(caps, dict) else {}
    defaults = research_cfg.get("defaults", {}) if isinstance(research_cfg, dict) else {}
    control_plane = defaults.get("control_plane", {}) if isinstance(defaults, dict) else {}

    overrides = control_plane.get("overrides") if isinstance(control_plane.get("overrides"), dict) else {}
    scorecard = control_plane.get("scorecard") if isinstance(control_plane.get("scorecard"), dict) else {}

    return {
        "overrides": overrides,
        "scorecard": scorecard,
        "constraints_projection": {
            "provider_runtime_overrides": overrides,
            "provider_runtime_scorecard": scorecard,
        },
    }


@router.patch("/retrieval/control-plane")
def patch_retrieval_control_plane(
    patch_data: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can patch retrieval control plane")
    if not isinstance(patch_data, dict):
        raise HTTPException(status_code=400, detail="Patch payload must be an object")

    kernel = getattr(request.app.state, "kernel", None)
    config_manager = getattr(kernel, "config_manager", None) if kernel else None
    if not config_manager:
        raise HTTPException(status_code=500, detail="Config manager not available")

    raw_config: Dict[str, Any] = {}
    try:
        if os.path.exists(config_manager.config_file):
            with open(config_manager.config_file, "r", encoding="utf-8") as handle:
                raw_config = json.load(handle) or {}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read raw config: {exc}")

    caps = raw_config.setdefault("capabilities", {})
    if not isinstance(caps, dict):
        raise HTTPException(status_code=500, detail="Invalid capabilities config shape")
    research_cfg = caps.setdefault("research_retrieve", {})
    if not isinstance(research_cfg, dict):
        raise HTTPException(status_code=500, detail="Invalid research_retrieve config shape")
    defaults = research_cfg.setdefault("defaults", {})
    if not isinstance(defaults, dict):
        raise HTTPException(status_code=500, detail="Invalid research_retrieve defaults shape")
    control_plane = defaults.setdefault("control_plane", {})
    if not isinstance(control_plane, dict):
        raise HTTPException(status_code=500, detail="Invalid control_plane config shape")

    merged = _merge_patch_preserving_masked(control_plane, patch_data)
    overrides = merged.get("overrides") if isinstance(merged.get("overrides"), dict) else {}
    scorecard = merged.get("scorecard") if isinstance(merged.get("scorecard"), dict) else {}
    control_plane["overrides"] = overrides
    control_plane["scorecard"] = scorecard
    defaults["control_plane"] = control_plane
    research_cfg["defaults"] = defaults
    caps["research_retrieve"] = research_cfg
    raw_config["capabilities"] = caps

    try:
        with open(config_manager.config_file, "w", encoding="utf-8") as handle:
            json.dump(raw_config, handle, indent=4)
        config_manager.load()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {exc}")

    db.add(
        AuditLog(
            user_id=user.id,
            username=user.username,
            action="patch_retrieval_control_plane",
            target="research_retrieve.control_plane",
            details=json.dumps({"keys": sorted(list(patch_data.keys()))}),
        )
    )
    db.commit()

    return {
        "status": "updated",
        "overrides": overrides,
        "scorecard": scorecard,
        "constraints_projection": {
            "provider_runtime_overrides": overrides,
            "provider_runtime_scorecard": scorecard,
        },
    }


@router.get("/{capability_id}/icon/{size}")
def get_capability_icon(
    capability_id: str,
    size: str,
    user: User = Depends(get_current_user),
):
    """
    Serves a capability icon asset from its internal assets folder.
    Protected by authentication.
    """
    folder = os.path.join(CAPABILITIES_DIR, capability_id)
    contract_path = os.path.join(folder, "contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=404, detail="Capability found")

    try:
        contract = load_contract_v1(contract_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Invalid contract: {exc}")

    assets = contract.capability.assets
    filename = None
    
    # Resolve the requested size to a filename
    if size == "svg":
        filename = assets.icon_svg
    elif size == "16x16" or size == "16":
        filename = assets.icon_16 or assets.icon_svg
    elif size == "32x32" or size == "32":
        filename = assets.icon_32 or assets.icon_svg
    elif size == "64x64" or size == "64":
        filename = assets.icon_64 or assets.icon_svg
    else:
        # Generic fallback to SVG if size is unknown
        filename = assets.icon_svg

    if not filename:
        raise HTTPException(status_code=404, detail="Icon version not found")

    # Sanitize path to prevent traversal
    asset_path = os.path.abspath(os.path.join(folder, filename))
    if not asset_path.startswith(os.path.abspath(folder)):
         raise HTTPException(status_code=403, detail="Access denied")

    if not os.path.exists(asset_path):
        raise HTTPException(status_code=404, detail="Icon file missing")

    return FileResponse(asset_path)


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
        if kernel and getattr(kernel, "capability_registry", None):
            registry = kernel.capability_registry
            capability_instance = registry.capabilities.get(capability_id) if hasattr(registry, "capabilities") else None
            if capability_instance is not None:
                try:
                    capability_instance.config = dict(capability_config)
                except Exception:
                    pass
            if hasattr(registry, "refresh_retrieval_offer"):
                registry.refresh_retrieval_offer(capability_id)
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
                "assets": metadata.get("assets"),
            }
        )
    return rows
