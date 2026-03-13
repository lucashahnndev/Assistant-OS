from __future__ import annotations

from abc import ABC
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from server.core.secret_manager import resolve_secret_ref


@dataclass(frozen=True)
class ProviderAuthField:
    key: str
    type: str
    title: str
    required: bool = False
    description: str = ""
    placeholder: str = ""


@dataclass(frozen=True)
class ProviderConfigField:
    key: str
    type: str
    title: str
    required: bool = False
    description: str = ""
    placeholder: str = ""
    default: Any = None


@dataclass(frozen=True)
class ProviderAuthMetadata:
    mode: str
    connectable: bool = False
    fields: List[ProviderAuthField] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderMetadata:
    key: str
    display_name: str
    description: str = ""
    auth: ProviderAuthMetadata = field(default_factory=lambda: ProviderAuthMetadata(mode="none"))
    config_fields: List[ProviderConfigField] = field(default_factory=list)
    default_scopes: List[str] = field(default_factory=list)

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "description": self.description,
            "auth": asdict(self.auth),
            "config_fields": [asdict(field) for field in self.config_fields],
            "default_scopes": list(self.default_scopes),
        }


class ExternalAccountProvider(ABC):
    metadata: ProviderMetadata

    def get_metadata(self) -> ProviderMetadata:
        return self.metadata

    def _get_raw_value(self, provider_config: Dict[str, Any], key: str) -> Any:
        return provider_config.get(key)

    def get_resolved_value(self, provider_config: Dict[str, Any], key: str) -> str:
        return resolve_secret_ref(self._get_raw_value(provider_config, key))

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        issues: List[str] = []

        for field in self.metadata.auth.fields:
            raw = self._get_raw_value(provider_config, field.key)
            text = str(raw or "").strip()
            if field.required and not text:
                issues.append(f"Missing {field.key}")
                continue
            if field.type == "secret_ref" and text and not text.startswith("ENV_"):
                issues.append(f"{field.key} must be an ENV_ secret reference")

        for field in self.metadata.config_fields:
            raw = self._get_raw_value(provider_config, field.key)
            text = str(raw or "").strip() if raw is not None else ""
            if field.required and not text:
                issues.append(f"Missing {field.key}")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }

    def build_authorize_url(
        self,
        provider_config: Dict[str, Any],
        state: Optional[str] = None,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        return None
