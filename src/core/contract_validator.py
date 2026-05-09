from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.errors import ErrorCode, SyntaxError as AgentSyntaxError
from core.provider_result import ProviderResult


@dataclass
class ContractValidationResult:
    ok: bool
    error_code: Optional[ErrorCode] = None
    error_type: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    parsed: Dict[str, Any] = field(default_factory=dict)


class ContractValidator:
    """
    Structural-only validation for provider output.
    No semantic repair, no action interpretation, no parameter correction.
    """

    REQUIRED_PROVIDER_FIELDS = ("provider_name", "model")
    REQUIRED_RAW_FIELDS = ("raw_text",)

    @classmethod
    def validate(cls, provider_result: ProviderResult, *, strict_mode: bool = False) -> ContractValidationResult:
        if not isinstance(provider_result, ProviderResult):
            raise AgentSyntaxError(
                "Provider result must be a ProviderResult instance.",
                code=ErrorCode.PLANNER_INVALID_JSON,
                details={"reason": "provider_result_type"},
            )

        if not str(provider_result.provider_name or "").strip():
            return ContractValidationResult(
                ok=False,
                error_code=ErrorCode.PLANNER_INVALID_JSON,
                error_type="SyntaxError",
                message="Missing provider_name.",
                details={"field": "provider_name"},
            )
        if not str(provider_result.model or "").strip():
            return ContractValidationResult(
                ok=False,
                error_code=ErrorCode.PLANNER_INVALID_JSON,
                error_type="SyntaxError",
                message="Missing model.",
                details={"field": "model"},
            )
        raw_text = str(provider_result.raw_text or "")
        if not raw_text.strip():
            return ContractValidationResult(
                ok=False,
                error_code=ErrorCode.PLANNER_INVALID_JSON,
                error_type="SyntaxError",
                message="Missing raw_text.",
                details={"field": "raw_text"},
            )

        parsed = provider_result.parsed
        if parsed is None:
            return ContractValidationResult(
                ok=False,
                error_code=ErrorCode.PLANNER_INVALID_JSON,
                error_type="SyntaxError",
                message="Parsed payload is missing.",
                details={"field": "parsed"},
            )
        if not isinstance(parsed, dict):
            return ContractValidationResult(
                ok=False,
                error_code=ErrorCode.PLANNER_INVALID_JSON,
                error_type="SyntaxError",
                message="Parsed payload must be a JSON object.",
                details={"field": "parsed", "type": type(parsed).__name__},
            )

        return ContractValidationResult(
            ok=True,
            parsed=dict(parsed),
            details={"strict_mode": bool(strict_mode)},
        )

