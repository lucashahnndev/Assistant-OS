from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.models import User, AuditLog, ExternalAccountConnection
from ..auth import (
    get_password_hash, 
    verify_password, 
    create_access_token, 
    decode_access_token, 
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from ..core.token_vault import get_token_vault, TokenVaultError
from pydantic import BaseModel
from datetime import timedelta
import logging
import os
import json
from urllib import request as urllib_request
from urllib import parse as urllib_parse

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("AuthRoutes")

class LoginRequest(BaseModel):
    username: str
    password: str

class BootstrapRequest(BaseModel):
    username: str
    password: str
    display_name: str = None

@router.get("/initialized")
def is_initialized(db: Session = Depends(get_db)):
    """Check if any user exists in the system."""
    user_count = db.query(User).count()
    return {"initialized": user_count > 0}

@router.post("/login")
@router.post("/login/")
def login(request: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == request.username).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "uid": user.id}, expires_delta=access_token_expires
    )
    
    secure_cookie = os.getenv("AOSD_COOKIE_SECURE", "false").lower() in ("1", "true", "yes", "on")

    # Set httpOnly cookie
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        samesite="lax",
        secure=secure_cookie,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    
    # Audit Login
    audit = AuditLog(user_id=user.id, username=user.username, action="login", target="portal")
    db.add(audit)
    db.commit()

    return {"message": "Login successful"}

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out"}

@router.post("/bootstrap")
def bootstrap(request: BootstrapRequest, db: Session = Depends(get_db)):
    # Strict Check: Only allowed if NO users exist
    user_count = db.query(User).count()
    if user_count > 0:
        raise HTTPException(status_code=410, detail="System already initialized. Use normal login.")
    
    hashed_password = get_password_hash(request.password)
    new_user = User(
        username=request.username,
        display_name=request.display_name or request.username,
        password_hash=hashed_password,
        role="admin"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    logger.info(f"System Bootstrap completed. Admin '{new_user.username}' created.")
    return {"message": "System initialized successfully. Please login."}

@router.get("/me")
def read_users_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "display_name": current_user.display_name,
        "role": current_user.role,
        "created_at": current_user.created_at
    }


@router.get("/{provider}/callback", response_class=HTMLResponse)
def oauth_provider_callback(
    request: Request,
    provider: str,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    OAuth callback endpoint used by external account providers.
    It currently finalizes the browser popup flow and notifies the opener window.
    """
    provider_key = (provider or "").strip().lower()
    if not provider_key:
        raise HTTPException(status_code=400, detail="Invalid provider")

    def _resolve_env_ref(value: str) -> str:
        token = str(value or "").strip()
        if not token:
            return ""
        if token.startswith("ENV_"):
            return os.getenv(token) or os.getenv(token[4:]) or ""
        return token

    def _exchange_google_code_for_profile(auth_code: str) -> dict:
        kernel = getattr(request.app.state, "kernel", None)
        if not kernel or not hasattr(kernel, "config_manager"):
            raise RuntimeError("Kernel config unavailable")

        ext_cfg = kernel.config_manager.get("external_accounts", {}) or {}
        providers_cfg = ext_cfg.get("providers", {}) if isinstance(ext_cfg, dict) else {}
        google_cfg = providers_cfg.get("google", {}) if isinstance(providers_cfg, dict) else {}
        if not isinstance(google_cfg, dict):
            raise RuntimeError("Google provider config not found")

        client_id = _resolve_env_ref(google_cfg.get("client_id") or google_cfg.get("client_id_ref"))
        client_secret = _resolve_env_ref(google_cfg.get("client_secret") or google_cfg.get("client_secret_ref"))
        redirect_uri = str(google_cfg.get("redirect_uri") or "").strip()
        if not client_id or not client_secret or not redirect_uri:
            raise RuntimeError("Google OAuth config incomplete (client_id/client_secret/redirect_uri)")

        token_payload = urllib_parse.urlencode({
            "code": auth_code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")
        token_req = urllib_request.Request(
            "https://oauth2.googleapis.com/token",
            data=token_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib_request.urlopen(token_req, timeout=12) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))

        access_token = str(token_data.get("access_token") or "")
        if not access_token:
            raise RuntimeError("Google token exchange did not return access_token")

        userinfo_req = urllib_request.Request(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            method="GET",
        )
        with urllib_request.urlopen(userinfo_req, timeout=12) as resp:
            profile = json.loads(resp.read().decode("utf-8"))

        return {
            "profile": {
                "sub": profile.get("sub"),
                "name": profile.get("name"),
                "email": profile.get("email"),
                "email_verified": profile.get("email_verified"),
                "picture": profile.get("picture"),
                "locale": profile.get("locale"),
            },
            "tokens": {
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token"),
                "id_token": token_data.get("id_token"),
                "token_type": token_data.get("token_type"),
                "scope": token_data.get("scope"),
                "expires_in": token_data.get("expires_in"),
            }
        }

    ok = bool(code) and not bool(error)
    status_label = "success" if ok else "error"
    message = error or ("Authorization completed" if ok else "Authorization failed")
    profile = None
    tokens = None

    if ok and provider_key == "google":
        try:
            exchange = _exchange_google_code_for_profile(code)
            profile = exchange.get("profile")
            tokens = exchange.get("tokens")
        except Exception as exc:
            logger.warning("Google OAuth profile retrieval failed: %s", exc)
            ok = False
            status_label = "error"
            message = f"Google OAuth profile retrieval failed: {exc}"

    # Persist encrypted OAuth tokens per user/provider.
    if ok and tokens and profile:
        try:
            vault = get_token_vault()
            encrypted_payload = vault.encrypt_json(tokens)

            provider_account_id = str(profile.get("sub") or "").strip() or None
            account_email = str(profile.get("email") or "").strip() or None
            account_name = str(profile.get("name") or "").strip() or None
            token_expires_at = None
            try:
                exp_seconds = int(tokens.get("expires_in") or 0)
                if exp_seconds > 0:
                    from datetime import datetime, timezone, timedelta as _td
                    token_expires_at = datetime.now(timezone.utc) + _td(seconds=exp_seconds)
            except Exception:
                token_expires_at = None

            existing = (
                db.query(ExternalAccountConnection)
                .filter(
                    ExternalAccountConnection.user_id == current_user.id,
                    ExternalAccountConnection.provider == provider_key,
                    ExternalAccountConnection.provider_account_id == provider_account_id,
                )
                .first()
            )

            if existing:
                existing.account_email = account_email
                existing.account_name = account_name
                existing.profile_json = json.dumps(profile, ensure_ascii=False)
                existing.encrypted_tokens = encrypted_payload
                existing.token_expires_at = token_expires_at
                existing.scopes = str(tokens.get("scope") or "")
                existing.is_active = True
            else:
                db.add(
                    ExternalAccountConnection(
                        user_id=current_user.id,
                        provider=provider_key,
                        provider_account_id=provider_account_id,
                        account_email=account_email,
                        account_name=account_name,
                        profile_json=json.dumps(profile, ensure_ascii=False),
                        encrypted_tokens=encrypted_payload,
                        token_expires_at=token_expires_at,
                        scopes=str(tokens.get("scope") or ""),
                        is_active=True,
                    )
                )
            db.commit()
        except TokenVaultError as exc:
            logger.error("OAuth token persistence failed (vault): %s", exc)
            ok = False
            status_label = "error"
            message = str(exc)
        except Exception as exc:
            logger.exception("OAuth token persistence failed: %s", exc)
            ok = False
            status_label = "error"
            message = f"OAuth token persistence failed: {exc}"

    payload = {
        "type": "external-oauth-callback",
        "provider": provider_key,
        "status": status_label,
        "state": state or "",
        "error": error or "",
        "profile": profile,
    }
    payload_json = json.dumps(payload)

    # Keep this page standalone-friendly if popup cannot be auto-closed.
    return f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>OAuth Callback</title>
    <style>
      body {{ background:#090c16; color:#e5e7eb; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; padding:24px; }}
      .card {{ max-width:560px; margin:24px auto; border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:18px; background:rgba(255,255,255,0.03); }}
      .ok {{ color:#34d399; font-weight:700; }}
      .err {{ color:#f87171; font-weight:700; }}
      .meta {{ color:#9ca3af; font-size:12px; margin-top:8px; }}
    </style>
  </head>
  <body>
    <div class="card">
      <div class="{ 'ok' if ok else 'err' }">{ 'Authorization successful' if ok else 'Authorization failed' }</div>
      <div>{message}</div>
      <div class="meta">Provider: {provider_key}</div>
    </div>
    <script>
      (function() {{
        try {{
          var payload = {payload_json};
          if (window.opener && !window.opener.closed) {{
            window.opener.postMessage(payload, "*");
            setTimeout(function() {{ window.close(); }}, 250);
          }}
        }} catch (e) {{}}
      }})();
    </script>
  </body>
</html>
"""
