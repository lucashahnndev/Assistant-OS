from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ProviderMetadata:
    key: str
    display_name: str
    description: str = ""
    auth_modes: List[str] = field(default_factory=lambda: ["oauth2"])
    default_scopes: List[str] = field(default_factory=list)


class ExternalAccountProvider(ABC):
    metadata: ProviderMetadata

    def get_metadata(self) -> ProviderMetadata:
        return self.metadata

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        issues: List[str] = []
        mode = str(provider_config.get("auth_mode") or "").strip().lower()
        if mode and mode not in {m.lower() for m in self.metadata.auth_modes}:
            issues.append(f"Unsupported auth_mode '{mode}'")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }

    def build_authorize_url(self, provider_config: Dict[str, Any], state: Optional[str] = None) -> Optional[str]:
        return None
