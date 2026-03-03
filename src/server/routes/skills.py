from fastapi import APIRouter, Depends, HTTPException, Request
from ..auth import get_current_user
from ..core.models import User, AuditLog
from ..core.database import get_db
from sqlalchemy.orm import Session
import os
import json
import yaml # We need to check if PyYAML is installed, or use simple parsing
import re
from core.identity import PrincipalContext

try:
    import jsonschema
except ImportError:
    jsonschema = None

router = APIRouter(prefix="/api/skills", tags=["skills"])

# Path to skills directory
# src/server/routes/skills.py -> 3 levels up to src
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS_DIR = os.path.join(BASE_DIR, "skills")

def mask_config(config, schema):
    """Masks secret fields in config based on schema recursively."""
    if not isinstance(config, dict) or not isinstance(schema, dict):
        return config
        
    masked = config.copy()
    properties = schema.get("properties", {})
    
    for key, value in properties.items():
        if key in masked:
            if isinstance(value, dict) and value.get("x-secret") is True:
                masked[key] = "********"
            elif isinstance(value, dict) and value.get("type") == "object" and "properties" in value:
                masked[key] = mask_config(masked[key], value)
    return masked

def normalize_schema(raw_config):
    """Recursively converts contract-style config into standard JSON Schema properties."""
    if not isinstance(raw_config, dict):
        return raw_config
    
    properties = {}
    for key, val in raw_config.items():
        if not isinstance(val, dict):
            properties[key] = val
            continue
            
        # Check if it's a leaf node (has type/description/etc)
        is_leaf = "type" in val or "default" in val or "description" in val or "enum" in val
        
        if is_leaf:
            if val.get("type") == "object" and "properties" in val:
                val["properties"] = normalize_schema(val["properties"])
            properties[key] = val
        else:
            properties[key] = {
                "type": "object",
                "properties": normalize_schema(val)
            }
    return properties

def validate_config(config, schema):
    """Validates config against schema, returns errors and missing fields."""
    if not jsonschema or not schema:
        return [], []
    
    errors = []
    missing = []
    
    validator = jsonschema.Draft202012Validator(schema)
    for error in validator.iter_errors(config):
        if error.validator == "required":
            # Extract missing field name from error message or path
            missing.extend(list(error.validator_value))
        else:
            errors.append(error.message)
            
    # filter missing that are actually present
    missing = [m for m in missing if m not in config]
    return errors, missing


def _infer_risk_level(action_id: str) -> str:
    """
    Fallback risk inference for UI catalog when contract metadata is missing.
    """
    high_risk_prefixes = [
        "shell.",
        "power.",
        "process.",
        "fs.",
        "system.control.power",
        "system.control.process.",
        "system.control.fs.",
        "system.control.service.manage",
    ]
    if any(action_id.startswith(p) for p in high_risk_prefixes):
        return "high"

    medium_risk_prefixes = [
        "web.search.",
        "maps.search.",
        "youtube.search.",
        "deezer.search.",
        "spotify.search.",
        "vision.",
        "system.control.network.",
        "system.control.screenshot",
        "system.control.process.list",
    ]
    if any(action_id.startswith(p) for p in medium_risk_prefixes):
        return "medium"

    return "low"

@router.get("/")
def list_skills(request: Request, user: User = Depends(get_current_user)):
    """
    Lists all available skills with validation status and masked config.
    """
    kernel = getattr(request.app.state, "kernel", None)
    registry = getattr(kernel, "skill_registry", None) if kernel else None
    
    # Discovery from directory (to find all, even disabled/unloaded ones)
    skills_map = {}
    if os.path.exists(SKILLS_DIR):
        for item in os.listdir(SKILLS_DIR):
            manifest_path = os.path.join(SKILLS_DIR, item, "contract.json")
            schema_path = os.path.join(SKILLS_DIR, item, "config.schema.json")
            
            if os.path.exists(manifest_path):
                # We use the new namespacing logic: name from contract
                try:
                    with open(manifest_path, 'r') as f:
                        contract = json.load(f)
                    
                    schema = {}
                    if os.path.exists(schema_path):
                        with open(schema_path, 'r') as f:
                            schema = json.load(f)
                    elif "config" in contract:
                        schema = {
                            "type": "object",
                            "properties": normalize_schema(contract["config"])
                        }
                    
                    # Parse actions robustly
                    contract_actions = contract.get("actions", [])
                    actions_list = []
                    skill_namespace = contract.get("name", item).lower().replace(" ", ".")
                    
                    if isinstance(contract_actions, list):
                        for a in contract_actions:
                            if not isinstance(a, dict): continue
                            action_id = a.get('id') or f"{skill_namespace}.{a.get('name') or a.get('handler')}"
                            actions_list.append(action_id)
                    elif isinstance(contract_actions, dict):
                        for action_key, action_data in contract_actions.items():
                            action_id = f"{skill_namespace}.{action_key}"
                            if isinstance(action_data, dict) and action_data.get('id'):
                                action_id = action_data['id']
                            actions_list.append(action_id)

                    skill_id = item # Folder name is the primary key for config
                    skills_map[skill_id] = {
                        "id": skill_id,
                        "name": contract.get("name", item),
                        "description": contract.get("description", ""),
                        "actions": actions_list,
                        "config_schema": schema,
                        "enabled": False,
                        "config": {},
                        "validation_errors": [],
                        "missing_required": []
                    }
                except Exception as e:
                    # Log error but don't fail discovery
                    print(f"Error parsing skill contract for {item}: {e}")
                    continue

    # Merge with Config and Registry
    config_manager = getattr(kernel, "config_manager", None) if kernel else None
    config = config_manager.config_data if config_manager else {}
    skills_config = config.get("skills", {})

    for skill_id, skill_data in skills_map.items():
        # Get effective config
        s_config = skills_config.get(skill_id, {})
        skill_data['enabled'] = s_config.get('enabled', False)
        
        # Validation
        errors, missing = validate_config(s_config, skill_data['config_schema'])
        skill_data['validation_errors'] = errors
        skill_data['missing_required'] = missing
        
        # Mask config
        skill_data['config'] = mask_config(s_config, skill_data['config_schema'])

    return list(skills_map.values())

@router.patch("/{skill_id}/config")
def update_skill_config(skill_id: str, patch_data: dict, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can configure skills")
        
    kernel = getattr(request.app.state, "kernel", None)
    config_manager = getattr(kernel, "config_manager", None) if kernel else None
    
    if not config_manager:
        raise HTTPException(status_code=500, detail="Config manager not available")
    
    # 1. Load RAW config from disk (do not use substituted config_data for persistence)
    raw_config = {}
    try:
        if os.path.exists(config_manager.config_file):
            with open(config_manager.config_file, "r", encoding="utf-8") as f:
                raw_config = json.load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read raw config: {e}")

    raw_skills_config = raw_config.get("skills", {})
    skill_config = raw_skills_config.get(skill_id, {}).copy()
    
    # 2. Apply patch (preserving special types if needed, but JSON is simple)
    # Don't allow overwriting secrets with mask
    for k, v in patch_data.items():
        if v == "********": continue # Skip masked values
        skill_config[k] = v
        
    # 3. Validate against schema
    schema = {}
    schema_path = os.path.join(SKILLS_DIR, skill_id, "config.schema.json")
    if os.path.exists(schema_path):
        with open(schema_path, 'r') as f:
            schema = json.load(f)
    else:
        manifest_path = os.path.join(SKILLS_DIR, skill_id, "contract.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, 'r') as f:
                contract = json.load(f)
                if "config" in contract:
                    schema = {
                        "type": "object",
                        "properties": normalize_schema(contract["config"])
                    }
            
    errors, missing = validate_config(skill_config, schema)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors, "missing": missing})

    # 4. Persistence via RAW config (preserves ENV_* placeholders)
    if "skills" not in raw_config:
        raw_config["skills"] = {}
    raw_config["skills"][skill_id] = skill_config

    # Save to disk
    try:
        with open(config_manager.config_file, "w", encoding="utf-8") as f:
            json.dump(raw_config, f, indent=4)
        config_manager.load() # Refresh
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")

    # Audit
    payload_preview = {k: "***" if "key" in k.lower() or "secret" in k.lower() else v for k,v in patch_data.items()}
    db.add(AuditLog(
        user_id=user.id, 
        username=user.username,
        action="patch_skill_config", 
        target=skill_id,
        details=json.dumps(payload_preview)
    ))
    db.commit()
    
    return {
        "status": "updated", 
        "config": mask_config(skill_config, schema),
        "validation_errors": errors,
        "missing_required": missing
    }

@router.post("/{skill_id}/toggle")
def toggle_skill(skill_id: str, enable: bool, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # ... (keeping existing toggle but using ConfigManager if possible)
    # Similar to patch but just for enabled
    return update_skill_config(skill_id, {"enabled": enable}, request, user, db)

@router.get("/registry")
def get_skill_registry(
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
    
    registry = kernel.skill_registry
    allowed_actions_set = None

    # Optional principal-scoped catalog for least-privilege UI/agents.
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

    actions = []
    
    for action_id, skill in sorted(registry.action_map.items(), key=lambda x: x[0]):
        if allowed_actions_set is not None and action_id not in allowed_actions_set:
            continue

        metadata = registry.get_action_metadata(action_id) if hasattr(registry, "get_action_metadata") else {}
        if not isinstance(metadata, dict):
            metadata = {}

        desc = metadata.get("description") or "No description available."
        risk_level = str(metadata.get("risk_level") or "").strip().lower()
        if risk_level not in {"low", "medium", "high"}:
            risk_level = _infer_risk_level(action_id)

        actions.append({
            "id": action_id,
            "skill_name": skill.name,
            "namespace": getattr(skill, "_namespace", "") or ".".join(action_id.split(".")[:-1]),
            "description": desc,
            "risk_level": risk_level
        })
            
    return actions
