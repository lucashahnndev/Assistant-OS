from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.errors import AgentSemanticError, ErrorCode
from utils.schema_utils import validate_json_instance, ValidationError, SchemaError
from utils.logging_config import get_logger

logger = get_logger("ActionGateway")


@dataclass
class ActionCanonicalizationResult:
    ok: bool
    action_id: str = ""
    error_code: Optional[ErrorCode] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionValidationResult:
    ok: bool
    error_code: Optional[ErrorCode] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionDecision:
    outcome: str
    action_id: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class ActionCanonicalizer:
    """
    Explicit alias mapping only. No fuzzy matching, no heuristics.
    """

    def __init__(self, alias_map: Optional[Dict[str, str]] = None):
        self.alias_map = {str(k).strip().lower(): str(v).strip() for k, v in (alias_map or {}).items() if str(k).strip() and str(v).strip()}

    def canonicalize(self, action_id: str, capability_registry: Any = None) -> ActionCanonicalizationResult:
        raw = str(action_id or "").strip()
        if not raw:
            return ActionCanonicalizationResult(False, error_code=ErrorCode.TOOL_NOT_FOUND, message="Missing action_id.", details={"reason": "missing_action_id"})
        normalized = raw.lower()
        if normalized in self.alias_map:
            return ActionCanonicalizationResult(True, action_id=self.alias_map[normalized], details={"mapping": "explicit_alias"})
        if capability_registry is not None and hasattr(capability_registry, "get_capability_for_action"):
            capability = capability_registry.get_capability_for_action(raw)
            if capability:
                return ActionCanonicalizationResult(True, action_id=raw, details={"mapping": "exact_registry"})
        return ActionCanonicalizationResult(False, error_code=ErrorCode.TOOL_NOT_FOUND, message=f"Unmapped action_id '{raw}'.", details={"reason": "unmapped_action_id"})


class ActionValidator:
    """
    Structural + capability validation only. No repair, no fallback.
    """

    def validate(
        self,
        *,
        action_id: str,
        params: Dict[str, Any],
        allowed_actions: Optional[List[str]],
        capability_registry: Any,
        capability_metadata: Optional[Dict[str, Any]] = None,
    ) -> ActionValidationResult:
        allowed = {str(x).strip() for x in (allowed_actions or []) if str(x or "").strip()}
        if allowed and action_id not in allowed:
            return ActionValidationResult(False, error_code=ErrorCode.TOOL_NOT_FOUND, message=f"Action '{action_id}' is outside the allowed set.", details={"action_id": action_id})
        capability = capability_registry.get_capability_for_action(action_id) if capability_registry else None
        if not capability:
            return ActionValidationResult(False, error_code=ErrorCode.TOOL_NOT_FOUND, message=f"Action '{action_id}' is not registered.", details={"action_id": action_id})
        if not isinstance(params, dict):
            return ActionValidationResult(False, error_code=ErrorCode.TOOL_INVALID_INPUT, message="params must be an object.", details={"action_id": action_id})
        metadata = capability_metadata or {}
        schema = metadata.get("parameters") if isinstance(metadata, dict) else None
        if schema:
            try:
                validate_json_instance(instance=params, schema=schema)
            except ValidationError:
                return ActionValidationResult(False, error_code=ErrorCode.TOOL_INVALID_INPUT, message=f"Action '{action_id}' params failed validation.", details={"action_id": action_id})
            except SchemaError:
                return ActionValidationResult(False, error_code=ErrorCode.POLICY_BLOCKED, message=f"Action '{action_id}' schema is invalid.", details={"action_id": action_id})
        return ActionValidationResult(True, details={"action_id": action_id})


class ActionGateway:
    """
    Resolution facade only.
    It canonicalizes, validates, and returns a deterministic decision object.
    """

    def __init__(self, alias_map: Optional[Dict[str, str]] = None):
        self.canonicalizer = ActionCanonicalizer(alias_map=alias_map)
        self.validator = ActionValidator()

    def resolve(
        self,
        *,
        action_id: str,
        params: Dict[str, Any],
        allowed_actions: Optional[List[str]],
        capability_registry: Any,
        capability_metadata: Optional[Dict[str, Any]] = None,
        strict_mode: bool = False,
    ) -> ActionDecision:
        canonicalized = self.canonicalizer.canonicalize(action_id, capability_registry=capability_registry)
        if not canonicalized.ok:
            logger.warning(
                "ActionGateway resolve rejected | action_id=%s outcome=REJECT reason=%s",
                action_id,
                canonicalized.message,
            )
            if strict_mode:
                raise AgentSemanticError(
                    canonicalized.message,
                    code=canonicalized.error_code or ErrorCode.TOOL_NOT_FOUND,
                    details=canonicalized.details,
                )
            return ActionDecision("REJECT", action_id=action_id, details=canonicalized.details)

        validated = self.validator.validate(
            action_id=canonicalized.action_id,
            params=params,
            allowed_actions=allowed_actions,
            capability_registry=capability_registry,
            capability_metadata=capability_metadata,
        )
        if not validated.ok:
            logger.warning(
                "ActionGateway resolve rejected | action_id=%s outcome=REJECT reason=%s",
                canonicalized.action_id,
                validated.message,
            )
            if strict_mode:
                raise AgentSemanticError(
                    validated.message,
                    code=validated.error_code or ErrorCode.TOOL_INVALID_INPUT,
                    details=validated.details,
                )
            return ActionDecision("REJECT", action_id=canonicalized.action_id, details=validated.details)

        logger.info(
            "ActionGateway resolve accepted | action_id=%s outcome=EXECUTE",
            canonicalized.action_id,
        )
        return ActionDecision("EXECUTE", action_id=canonicalized.action_id, details={"action_id": canonicalized.action_id})

    def execute_action(
        self,
        *,
        action_id: str,
        params: Dict[str, Any],
        allowed_actions: Optional[List[str]],
        capability_registry: Any,
        capability_metadata: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        strict_mode: bool = False,
    ) -> Dict[str, Any]:
        decision = self.resolve(
            action_id=action_id,
            params=params,
            allowed_actions=allowed_actions,
            capability_registry=capability_registry,
            capability_metadata=capability_metadata,
            strict_mode=strict_mode,
        )
        if decision.outcome != "EXECUTE":
            logger.warning(
                "ActionGateway execute rejected | action_id=%s outcome=%s",
                action_id,
                decision.outcome,
            )
            return {
                "ok": False,
                "status": "error",
                "error_code": "ACTION_REJECTED",
                "error_details": dict(decision.details or {}),
            }
        if capability_registry is None or not hasattr(capability_registry, "dispatch"):
            logger.warning("ActionGateway execute failed | action_id=%s reason=registry_unavailable", decision.action_id)
            return {
                "ok": False,
                "status": "error",
                "error_code": "REGISTRY_UNAVAILABLE",
                "error_details": {"action_id": decision.action_id},
            }
        result = capability_registry.dispatch(decision.action_id, params or {}, context or {})
        logger.info(
            "ActionGateway execute completed | action_id=%s result_type=%s",
            decision.action_id,
            type(result).__name__,
        )
        return result
