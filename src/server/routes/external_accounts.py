from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..core.database import get_db
from ..core.models import ExternalAccountConnection, User
from integrations.external_accounts import get_provider_registry


router = APIRouter(prefix="/api/external-accounts", tags=["external_accounts"])


class AuthStartRequest(BaseModel):
    provider_key: str
    state: str | None = None


def _get_external_accounts_config(request: Request) -> dict:
    kernel = getattr(request.app.state, "kernel", None)
    if not kernel or not hasattr(kernel, "config_manager"):
        return {"enabled": True, "providers": {}}
    config = kernel.config_manager.get("external_accounts", {}) or {}
    if not isinstance(config, dict):
        return {"enabled": True, "providers": {}}
    providers = config.get("providers") or {}
    if not isinstance(providers, dict):
        providers = {}
    return {
        "enabled": config.get("enabled", True),
        "providers": providers,
    }


@router.get("/providers")
def list_providers(user: User = Depends(get_current_user), request: Request = None):
    registry = get_provider_registry()
    plugin_map = registry.all()
    ext_cfg = _get_external_accounts_config(request)
    configured = ext_cfg.get("providers", {})

    items = []
    for key, provider in plugin_map.items():
        meta = provider.get_metadata()
        provider_cfg = configured.get(key, {}) if isinstance(configured.get(key, {}), dict) else {}
        validation = provider.validate_config(provider_cfg)
        items.append({
            "key": meta.key,
            "display_name": meta.display_name,
            "description": meta.description,
            "auth_modes": meta.auth_modes,
            "default_scopes": meta.default_scopes,
            "configured": key in configured,
            "enabled": bool(provider_cfg.get("enabled", False)),
            "config_validation": validation,
        })

    return {
        "external_accounts_enabled": bool(ext_cfg.get("enabled", True)),
        "providers": sorted(items, key=lambda x: x["display_name"].lower()),
    }


@router.get("/connections")
def list_connections(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ExternalAccountConnection)
        .filter(
            ExternalAccountConnection.user_id == user.id,
            ExternalAccountConnection.is_active == True,
        )
        .order_by(ExternalAccountConnection.updated_at.desc())
        .all()
    )

    items = []
    for row in rows:
        profile = {}
        try:
            profile = json.loads(row.profile_json) if row.profile_json else {}
            if not isinstance(profile, dict):
                profile = {}
        except Exception:
            profile = {}

        items.append(
            {
                "id": row.id,
                "provider": row.provider,
                "provider_account_id": row.provider_account_id,
                "account": row.account_email or row.account_name or "Connected account",
                "status": "connected" if row.is_active else "inactive",
                "profile": {
                    "name": row.account_name or profile.get("name") or "",
                    "email": row.account_email or profile.get("email") or "",
                    "picture": profile.get("picture") or "",
                    "locale": profile.get("locale") or "",
                },
                "connected_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "scopes": row.scopes or "",
            }
        )

    return {"connections": items}


@router.delete("/connections/{connection_id}")
def remove_connection(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(ExternalAccountConnection)
        .filter(
            ExternalAccountConnection.id == connection_id,
            ExternalAccountConnection.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Connection not found")

    # Soft delete to preserve auditability while disabling future usage.
    row.is_active = False
    db.commit()
    return {"ok": True}


@router.post("/auth/start")
def start_auth(payload: AuthStartRequest, user: User = Depends(get_current_user), request: Request = None):
    provider_key = (payload.provider_key or "").strip().lower()
    if not provider_key:
        raise HTTPException(status_code=400, detail="provider_key is required")

    registry = get_provider_registry()
    provider = registry.get(provider_key)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_key}' not found")

    ext_cfg = _get_external_accounts_config(request)
    providers_cfg = ext_cfg.get("providers", {})
    provider_cfg = providers_cfg.get(provider_key)
    if not isinstance(provider_cfg, dict):
        raise HTTPException(status_code=400, detail=f"Provider '{provider_key}' is not configured")

    validation = provider.validate_config(provider_cfg)
    if not validation.get("valid", True):
        issues = validation.get("issues") or []
        detail = f"Provider '{provider_key}' config is invalid"
        if issues:
            detail = f"{detail}: " + "; ".join(str(i) for i in issues)
        raise HTTPException(status_code=400, detail=detail)

    authorize_url = provider.build_authorize_url(provider_cfg, state=payload.state)
    if not authorize_url:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_key}' cannot build authorize URL with current config. Check auth_mode/client_id/redirect_uri."
        )

    return {
        "provider": provider_key,
        "authorize_url": authorize_url,
    }
