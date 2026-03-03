from __future__ import annotations

import os
from urllib.parse import urlencode

from ..base import ExternalAccountProvider, ProviderMetadata


class GoogleProvider(ExternalAccountProvider):
    metadata = ProviderMetadata(
        key="google",
        display_name="Google",
        description="Google OAuth account for Google APIs.",
        auth_modes=["oauth2", "api_key"],
        default_scopes=["openid", "email", "profile"],
    )

    @staticmethod
    def _resolve_env_ref(value) -> str:
        token = str(value or "").strip()
        if not token:
            return ""
        if token.startswith("ENV_"):
            return os.getenv(token) or os.getenv(token[4:]) or ""
        return token

    def validate_config(self, provider_config):
        issues = []
        mode = str(provider_config.get("auth_mode", "oauth2")).strip().lower()
        if mode != "oauth2":
            issues.append("auth_mode must be oauth2 for Google OAuth start")

        client_id = self._resolve_env_ref(provider_config.get("client_id") or provider_config.get("client_id_ref"))
        redirect_uri = str(provider_config.get("redirect_uri") or "").strip()
        if not client_id:
            issues.append("Missing client_id (or ENV_ ref)")
        if not redirect_uri:
            issues.append("Missing redirect_uri")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }

    def build_authorize_url(self, provider_config, state=None):
        if str(provider_config.get("auth_mode", "oauth2")).lower() != "oauth2":
            return None

        client_id = self._resolve_env_ref(provider_config.get("client_id") or provider_config.get("client_id_ref"))
        redirect_uri = (provider_config.get("redirect_uri") or "").strip()
        scopes = provider_config.get("scopes") or self.metadata.default_scopes
        if not client_id or not redirect_uri:
            return None

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "scope": " ".join(scopes),
        }
        if state:
            params["state"] = state
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def get_provider() -> ExternalAccountProvider:
    return GoogleProvider()
