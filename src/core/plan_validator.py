import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional

from core.errors import ErrorCode
from core.resolution.action_plan import ActionPlan
from utils.schema_utils import SchemaError, ValidationError, validate_json_instance

logger = logging.getLogger("PlanValidator")

@dataclass
class ValidationResult:
    is_valid: bool
    error_code: Optional[ErrorCode] = None
    message: Optional[str] = None
    diagnostics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "error_code": (self.error_code.value if self.error_code is not None else None),
            "message": self.message,
            "diagnostics": self.diagnostics or {}
        }

class PlanValidator:
    """
    Deterministic validator for ActionPlans.
    Ensures plans are safe, viable, and syntactically correct before execution.
    """

    @staticmethod
    def validate(
        plan: ActionPlan, 
        capability_registry: Any,
        session: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Validates an ActionPlan against functional and semantic constraints.
        """
        if plan.action_id in {"reply", "error"}:
            return ValidationResult(is_valid=True)

        if capability_registry is None or not hasattr(capability_registry, "get_capability_for_action"):
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.TOOL_NOT_FOUND,
                message=f"Action '{plan.action_id}' cannot be validated because the capability registry is unavailable.",
                diagnostics={"action_id": plan.action_id, "reason": "registry_unavailable"},
            )

        # 1. Action Existence & Registry Integrity
        capability = capability_registry.get_capability_for_action(plan.action_id)
        if not capability:
            suggestions = []
            if hasattr(capability_registry, "suggest_actions"):
                try:
                    suggestions = capability_registry.suggest_actions(plan.action_id)
                except Exception:
                    suggestions = []
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.TOOL_NOT_FOUND,
                message=f"Action '{plan.action_id}' not registered.",
                diagnostics={
                    "action_id": plan.action_id, 
                    "suggestions": suggestions
                }
            )

        # 2. Capability Health Check (Session-level)
        tool_health = getattr(session, "tool_health", {})
        health = tool_health.get(plan.action_id, "HEALTHY")
        if health == "UNAVAILABLE":
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.SYSTEM_DRIVER_UNAVAILABLE,
                message=f"Action '{plan.action_id}' is UNAVAILABLE in this session due to repeated failures.",
                diagnostics={"action_id": plan.action_id, "health": "UNAVAILABLE", "recovery": "replan"}
            )

        # 3. Argument/Schema Validation (canonical contract only)
        action_metadata = {}
        if hasattr(capability_registry, "get_action_metadata"):
            try:
                action_metadata = capability_registry.get_action_metadata(plan.action_id) or {}
            except Exception:
                action_metadata = {}
        schema = action_metadata.get("parameters")

        if schema:
            try:
                validate_json_instance(instance=plan.args, schema=schema)
            except ValidationError as e:
                return ValidationResult(
                    is_valid=False,
                    error_code=ErrorCode.TOOL_INVALID_INPUT,
                    message=f"Schema validation failed for '{plan.action_id}': {e}",
                    diagnostics={
                        "action_id": plan.action_id,
                        "validation_error": str(e),
                        "provided_args": plan.args,
                    }
                )
            except SchemaError as e:
                logger.error(f"Internal Schema error in contract for '{plan.action_id}': {e}")
                return ValidationResult(
                    is_valid=False,
                    error_code=ErrorCode.POLICY_BLOCKED,
                    message=f"Invalid canonical parameter schema for '{plan.action_id}'.",
                    diagnostics={"action_id": plan.action_id, "schema_error": str(e)},
                )
            except Exception as e:
                logger.error(f"Validation engine error: {e}")
                return ValidationResult(
                    is_valid=False,
                    error_code=ErrorCode.POLICY_BLOCKED,
                    message=f"Validation engine failed for '{plan.action_id}'.",
                    diagnostics={"action_id": plan.action_id, "error": str(e)},
                )

        # 4. Dependency Validation (Basic step dependencies)
        # Browser Control namespace manages its own runtime/session lifecycle and
        # must not be blocked by legacy `browser.open` preconditions.
        if plan.action_id.startswith("browser.") and not plan.action_id.startswith("browser.control."):
            drivers_state = getattr(session, "drivers_state", {})
            if "browser" not in drivers_state and "playwright" not in drivers_state:
                return ValidationResult(
                    is_valid=False,
                    error_code=ErrorCode.SYSTEM_DRIVER_UNAVAILABLE,
                    message=f"Action '{plan.action_id}' requires an active browser session.",
                    diagnostics={"missing_dependency": "browser_session"}
                )

        # 5. Policy & Side-Effect Safety
        metadata = action_metadata
        if not metadata and hasattr(capability_registry, "get_action_metadata"):
            try:
                metadata = capability_registry.get_action_metadata(plan.action_id) or {}
            except Exception:
                metadata = {}
        side_effect = metadata.get("side_effect", "none")
        if side_effect == "destructive":
            # Policy: Destructive actions in system turns must be authorized
            is_system_turn = bool(context and context.get("is_system_turn"))
            is_authorized = bool(context and context.get("authorized_destructive_actions", False))
            if is_system_turn and not is_authorized:
                 return ValidationResult(
                    is_valid=False,
                    error_code=ErrorCode.POLICY_BLOCKED,
                    message=f"Destructive action '{plan.action_id}' is restricted during autonomous system turns.",
                    diagnostics={"side_effect": "destructive", "policy_code": "AUTONOMOUS_DESTRUCTIVE_LOCKED"}
                )

        return ValidationResult(is_valid=True)
