from __future__ import annotations

import os
import secrets as py_secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import get_optional_user
from ..core.database import get_db
from ..core.models import User
from ..core.secret_manager import (
    SecretVaultError,
    audit_env_file,
    delete_secret,
    import_env_file,
    list_secret_entries,
    list_secret_refs,
    upsert_secret,
    vault_metadata,
)


router = APIRouter(prefix="/api/secrets", tags=["secrets"])


def _resolve_env_path() -> str:
    data_dir = os.environ.get("AOSD_DATA_DIR") or os.path.join(os.getcwd(), "data")
    return os.path.join(data_dir, ".env")


def _ensure_secret_access(request: Request, db: Session) -> Dict[str, Any]:
    management_key = (
        os.getenv("SECRET_MANAGEMENT_KEY", "").strip()
    )
    provided_key = str(
        request.headers.get("X-Secret-Management-Key")
        or ""
    ).strip()

    if management_key and provided_key and py_secrets.compare_digest(provided_key, management_key):
        return {"mode": "management_key", "user": None}

    user: Optional[User] = get_optional_user(request, db)
    if user and str(getattr(user, "role", "")).lower() == "admin":
        return {"mode": "web_admin", "user": user}

    if management_key:
        raise HTTPException(
            status_code=403,
            detail="Secret management requires admin web session or valid X-Secret-Management-Key.",
        )
    raise HTTPException(
        status_code=403,
        detail="Secret management requires admin web session.",
    )


def _reload_kernel_env(request: Request, env_key: str, config_ref: str, value: Optional[str] = None) -> None:
    if value is not None:
        os.environ[env_key] = value
        os.environ[config_ref] = value
    else:
        os.environ.pop(env_key, None)
        os.environ.pop(config_ref, None)

    kernel = getattr(request.app.state, "kernel", None)
    if kernel and hasattr(kernel, "reload_config"):
        try:
            kernel.reload_config()
        except Exception:
            pass


@router.get("/refs")
def get_secret_refs(request: Request, db: Session = Depends(get_db)):
    _ensure_secret_access(request, db)
    refs = list_secret_refs()
    return {"keys": refs}


@router.get("/entries")
def get_secret_entries(request: Request, db: Session = Depends(get_db)):
    _ensure_secret_access(request, db)
    return {
        "entries": list_secret_entries(),
        "vault": vault_metadata(),
    }


@router.get("/audit-env")
def audit_env(request: Request, db: Session = Depends(get_db)):
    _ensure_secret_access(request, db)
    try:
        return audit_env_file(_resolve_env_path())
    except SecretVaultError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to audit .env import source: {exc}")


@router.post("/import-env")
def import_env(payload: dict, request: Request, db: Session = Depends(get_db)):
    access = _ensure_secret_access(request, db)
    overwrite = bool(payload.get("overwrite", False))
    try:
        result = import_env_file(_resolve_env_path(), overwrite=overwrite)
    except SecretVaultError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to import .env source: {exc}")

    kernel = getattr(request.app.state, "kernel", None)
    if kernel and hasattr(kernel, "reload_config"):
        try:
            kernel.reload_config()
        except Exception:
            pass

    return {
        "success": True,
        "mode": access["mode"],
        **result,
    }


@router.post("")
def create_or_update_secret(payload: dict, request: Request, db: Session = Depends(get_db)):
    access = _ensure_secret_access(request, db)
    key = str(payload.get("key") or "").strip()
    value = str(payload.get("value") or "").strip()
    overwrite = bool(payload.get("overwrite", False))
    if not key or not value:
        raise HTTPException(status_code=400, detail="Key and value are required")
    try:
        stored = upsert_secret(key=key, value=value, overwrite=overwrite)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SecretVaultError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to persist secret: {exc}")

    _reload_kernel_env(
        request=request,
        env_key=stored["env_key"],
        config_ref=stored["config_ref"],
        value=value,
    )

    return {
        "success": True,
        "key": stored["config_ref"],
        "stored_key": stored["env_key"],
        "mode": access["mode"],
        "storage": "vault",
    }


@router.delete("/{key}")
def remove_secret(key: str, request: Request, db: Session = Depends(get_db)):
    access = _ensure_secret_access(request, db)
    try:
        deleted = delete_secret(key=key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SecretVaultError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete secret: {exc}")

    _reload_kernel_env(
        request=request,
        env_key=deleted["env_key"],
        config_ref=deleted["config_ref"],
        value=None,
    )

    return {
        "success": True,
        "deleted_key": deleted["config_ref"],
        "mode": access["mode"],
        "storage": "vault",
    }
