from __future__ import annotations

from urllib.parse import urlencode

from ..base import ExternalAccountProvider, ProviderMetadata


class MicrosoftProvider(ExternalAccountProvider):
    metadata = ProviderMetadata(
        key="microsoft",
        display_name="Microsoft",
        description="Microsoft identity platform OAuth account.",
        auth_modes=["oauth2"],
        default_scopes=["openid", "profile", "email", "offline_access"],
    )

    def build_authorize_url(self, provider_config, state=None):
        client_id = (provider_config.get("client_id") or "").strip()
        redirect_uri = (provider_config.get("redirect_uri") or "").strip()
        tenant = (provider_config.get("tenant") or "common").strip()
        scopes = provider_config.get("scopes") or self.metadata.default_scopes
        if not client_id or not redirect_uri:
            return None

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
        }
        if state:
            params["state"] = state
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}"


def get_provider() -> ExternalAccountProvider:
    return MicrosoftProvider()
