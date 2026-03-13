from __future__ import annotations

from urllib.parse import urlencode
from typing import Any, Dict, Optional

from ..base import ExternalAccountProvider, ProviderAuthField, ProviderAuthMetadata, ProviderConfigField, ProviderMetadata


class GoogleProvider(ExternalAccountProvider):
    metadata = ProviderMetadata(
        key="google",
        display_name="Google",
        description="Google OAuth account for Google APIs.",
        auth=ProviderAuthMetadata(
            mode="oauth2",
            connectable=True,
            fields=[
                ProviderAuthField(
                    key="client_id",
                    type="secret_ref",
                    title="Client ID Ref",
                    required=True,
                    placeholder="ENV_GOOGLE_CLIENT_ID",
                ),
                ProviderAuthField(
                    key="client_secret",
                    type="secret_ref",
                    title="Client Secret Ref",
                    required=True,
                    placeholder="ENV_GOOGLE_CLIENT_SECRET",
                ),
            ],
        ),
        config_fields=[
            ProviderConfigField(
                key="redirect_uri",
                type="string",
                title="Redirect URI",
                required=True,
                placeholder="http://localhost:8000/api/auth/google/callback",
            ),
        ],
        default_scopes=["openid", "email", "profile"],
    )

    def validate_config(self, provider_config):
        validation = super().validate_config(provider_config)
        issues = list(validation.get("issues") or [])
        client_id = self.get_resolved_value(provider_config, "client_id")
        redirect_uri = str(provider_config.get("redirect_uri") or "").strip()
        if not client_id:
            issues.append("Missing usable client_id")
        if not redirect_uri:
            issues.append("Missing redirect_uri")
        return {"valid": len(issues) == 0, "issues": issues}

    def build_authorize_url(
        self,
        provider_config: Dict[str, Any],
        state: Optional[str] = None,
        extra_params: Optional[Dict[str, Any]] = None,
    ):
        client_id = self.get_resolved_value(provider_config, "client_id")
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
        if isinstance(extra_params, dict):
            for k, v in extra_params.items():
                if v is None:
                    continue
                params[str(k)] = str(v)
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def get_provider() -> ExternalAccountProvider:
    return GoogleProvider()
