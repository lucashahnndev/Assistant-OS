from __future__ import annotations

import datetime
import json
import logging
from typing import Any, Dict, Optional
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from server.core.database import SessionLocal
from server.core.models import ExternalAccountConnection
from server.core.secret_manager import resolve_secret_ref
from server.core.token_vault import TokenVaultError, get_token_vault

logger = logging.getLogger("GoogleAuthShared")


def _resolve_secret_value(value: Any) -> str:
    return str(resolve_secret_ref(str(value or "").strip()) or "").strip()


def _extract_portal_user_id(context: Dict[str, Any]) -> Optional[int]:
    try:
        # Preferred stable path for web-authenticated requests
        session = context.get("session") if isinstance(context, dict) else None
        if session and isinstance(getattr(session, "context", None), dict):
            raw = session.context.get("portal_user_id")
            if raw is not None and str(raw).strip():
                return int(str(raw))
            principal = session.context.get("principal_context")
            if isinstance(principal, dict):
                sender_id = str(principal.get("sender_id") or "")
                if sender_id.startswith("user_"):
                    return int(sender_id.split("_", 1)[1])

        raw_direct = context.get("portal_user_id") if isinstance(context, dict) else None
        if raw_direct is not None and str(raw_direct).strip():
            return int(str(raw_direct))
    except Exception:
        return None
    return None


def _get_google_provider_config(kernel: Any) -> Dict[str, Any]:
    if not kernel or not hasattr(kernel, "config_manager"):
        return {}
    ext_cfg = kernel.config_manager.get("external_accounts", {}) or {}
    providers = ext_cfg.get("providers", {}) if isinstance(ext_cfg, dict) else {}
    google_cfg = providers.get("google", {}) if isinstance(providers, dict) else {}
    return google_cfg if isinstance(google_cfg, dict) else {}


def _get_google_accounts_from_config(kernel: Any):
    """Returns the list of google accounts from config.json external_accounts.accounts[]"""
    if not kernel or not hasattr(kernel, "config_manager"):
        return []
    ext_cfg = kernel.config_manager.get("external_accounts", {}) or {}
    if not isinstance(ext_cfg, dict):
        return []
    accounts = ext_cfg.get("accounts", [])
    if not isinstance(accounts, list):
        return []
    return [a for a in accounts if isinstance(a, dict) and str(a.get("provider", "")).lower() == "google"]


def _resolve_google_auth_from_config(kernel: Any) -> Optional[Dict[str, Any]]:
    """
    NOTE: Tokens are stored encrypted in the ExternalAccountConnection DB table,
    not in config.json. This function is intentionally a no-op — the DB path
    in resolve_google_request_auth handles all OAuth auth resolution.
    config.json only holds provider settings (client_id, client_secret, etc.),
    not user OAuth tokens.
    """
    return None


def _refresh_google_token_if_needed(
    *,
    kernel: Any,
    token_payload: Dict[str, Any],
    token_expires_at: Optional[datetime.datetime],
) -> Dict[str, Any]:
    now = datetime.datetime.now(datetime.timezone.utc)
    if token_expires_at:
        expires_at = token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
        # Keep small safety window
        if expires_at > (now + datetime.timedelta(seconds=60)):
            return token_payload

    access_token = str(token_payload.get("access_token") or "").strip()
    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    if access_token and not token_expires_at:
        return token_payload
    if not refresh_token:
        return token_payload

    cfg = _get_google_provider_config(kernel)
    client_id = _resolve_secret_value(cfg.get("client_id"))
    client_secret = _resolve_secret_value(cfg.get("client_secret"))
    if not client_id or not client_secret:
        logger.warning("Google token refresh skipped: missing client_id/client_secret")
        return token_payload

    try:
        body = urllib_parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        req = urllib_request.Request(
            "https://oauth2.googleapis.com/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=10) as resp:
            refreshed = json.loads(resp.read().decode("utf-8"))
        new_access = str(refreshed.get("access_token") or "").strip()
        if not new_access:
            return token_payload

        merged = dict(token_payload)
        merged["access_token"] = new_access
        merged["token_type"] = refreshed.get("token_type") or merged.get("token_type")
        merged["scope"] = refreshed.get("scope") or merged.get("scope")
        if refreshed.get("refresh_token"):
            merged["refresh_token"] = refreshed.get("refresh_token")
        merged["expires_in"] = refreshed.get("expires_in")
        merged["_refreshed_at"] = now.isoformat()
        return merged
    except Exception as exc:
        logger.warning("Google token refresh failed: %s", exc)
        return token_payload


def resolve_google_request_auth(
    *,
    context: Dict[str, Any],
    kernel: Any,
    api_key_fallback: Optional[str] = None,
    requested_source: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Shared resolver for Google-authenticated HTTP requests.

    Returns:
      {
        mode: oauth|api_key|none,
        headers: dict,
        params: dict,
        token_payload: dict|None,
        reason: str|None,
      }
    """
    source = str(requested_source or "auto").strip().lower()
    if source not in {"auto", "linked_account", "api_key"}:
        source = "auto"

    user_id = _extract_portal_user_id(context or {})

    if source in {"auto", "linked_account"}:
        db = SessionLocal()
        try:
            # Unified User Approach: Use the first active Google connection found in the system.
            # This ignores specific portal_user_id mappings to simplify sync across multiple interfaces.
            conn = (
                db.query(ExternalAccountConnection)
                .filter(
                    ExternalAccountConnection.provider == "google",
                    ExternalAccountConnection.is_active == True,
                )
                .order_by(ExternalAccountConnection.updated_at.desc())
                .first()
            )
            
            if not conn and source == "linked_account":
                return {
                    "mode": "none",
                    "headers": {},
                    "params": {},
                    "token_payload": None,
                    "reason": "No active Google connection found in the system.",
                }
            if conn:
                vault = get_token_vault()
                tokens = vault.decrypt_json(conn.encrypted_tokens)
                refreshed = _refresh_google_token_if_needed(
                    kernel=kernel,
                    token_payload=tokens,
                    token_expires_at=conn.token_expires_at,
                )

                # Persist updated tokens if changed
                if refreshed != tokens:
                    conn.encrypted_tokens = vault.encrypt_json(refreshed)
                    exp = refreshed.get("expires_in")
                    try:
                        exp_i = int(exp)
                        if exp_i > 0:
                            conn.token_expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=exp_i)
                    except Exception:
                        pass
                    db.commit()

                access_token = str(refreshed.get("access_token") or "").strip()
                if access_token:
                    return {
                        "mode": "oauth",
                        "headers": {"Authorization": f"Bearer {access_token}"},
                        "params": {},
                        "token_payload": refreshed,
                        "reason": None,
                    }
        except TokenVaultError as exc:
            logger.warning("Google auth vault unavailable: %s", exc)
            if source == "linked_account":
                return {"mode": "none", "headers": {}, "params": {}, "token_payload": None, "reason": str(exc)}
        except Exception as exc:
            logger.warning("Google linked auth resolve failed: %s", exc)
            if source == "linked_account":
                return {"mode": "none", "headers": {}, "params": {}, "token_payload": None, "reason": str(exc)}
        finally:
            db.close()

    if source in {"auto", "api_key"}:
        api_key = str(api_key_fallback or "").strip()
        if api_key:
            return {
                "mode": "api_key",
                "headers": {},
                "params": {"key": api_key},
                "token_payload": None,
                "reason": None,
            }

    return {
        "mode": "none",
        "headers": {},
        "params": {},
        "token_payload": None,
        "reason": "No linked Google account token and no API key fallback available.",
    }
