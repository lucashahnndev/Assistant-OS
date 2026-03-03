from __future__ import annotations

from ..base import ExternalAccountProvider, ProviderMetadata


class AwsProvider(ExternalAccountProvider):
    metadata = ProviderMetadata(
        key="aws",
        display_name="AWS",
        description="AWS integrations, usually IAM/OIDC or key-based auth depending on service.",
        auth_modes=["oidc", "api_key", "custom"],
        default_scopes=[],
    )


def get_provider() -> ExternalAccountProvider:
    return AwsProvider()
