from __future__ import annotations

from ..base import ExternalAccountProvider, ProviderMetadata


class CloudflareProvider(ExternalAccountProvider):
    metadata = ProviderMetadata(
        key="cloudflare",
        display_name="Cloudflare",
        description="Cloudflare APIs via OAuth2 or API token.",
        auth_modes=["oauth2", "api_token"],
        default_scopes=[],
    )


def get_provider() -> ExternalAccountProvider:
    return CloudflareProvider()
