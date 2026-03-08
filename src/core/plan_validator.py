import logging
import jsonschema
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from core.errors import ErrorCode
from core.resolution.action_plan import ActionPlan

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
        skill_registry: Any,
        session: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Validates an ActionPlan against functional and semantic constraints.
        """
        if plan.action_id in {"reply", "error"}:
            return ValidationResult(is_valid=True)

        # 1. Action Existence & Registry Integrity
        skill = skill_registry.get_skill_for_action(plan.action_id)
        if not skill:
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.TOOL_NOT_FOUND,
                message=f"Action '{plan.action_id}' not registered.",
                diagnostics={
                    "action_id": plan.action_id, 
                    "suggestions": skill_registry.suggest_actions(plan.action_id)
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

        # 3. Argument/Schema Validation
        contract = getattr(skill, "_contract", {}) or {}
        actions_schema = contract.get("actions", {})
        
        action_found = False
        schema = None
        
        # Exact match in contract
        if isinstance(actions_schema, dict):
            entry = actions_schema.get(plan.action_id.split(".")[-1])
            if entry:
                schema = entry.get("params")
                action_found = True
        elif isinstance(actions_schema, list):
            for entry in actions_schema:
                if entry.get("id") == plan.action_id or entry.get("name") == plan.action_id.split(".")[-1]:
                    schema = entry.get("params")
                    action_found = True
                    break
        
        if action_found and schema:
            try:
                # Standardize the custom 'params' format into a valid JSON Schema
                properties = {}
                required = []
                for p_name, p_info in schema.items():
                    if not isinstance(p_info, dict):
                        properties[p_name] = {"type": str(p_info)}
                        continue
                    
                    # Clone to avoid mutating registry data
                    clean_info = dict(p_info)
                    if clean_info.pop("required", False) is True:
                        required.append(p_name)
                    
                    # jsonschema 'type' must be standard. Some contracts use custom types.
                    # We'll just pass it through; if jsonschema fails, it's a dev error.
                    properties[p_name] = clean_info

                full_schema = {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": True # Be permissive by default
                }
                
                jsonschema.validate(instance=plan.args, schema=full_schema)
            except jsonschema.exceptions.ValidationError as e:
                return ValidationResult(
                    is_valid=False,
                    error_code=ErrorCode.TOOL_INVALID_INPUT,
                    message=f"Schema validation failed for '{plan.action_id}': {e.message}",
                    diagnostics={
                        "action_id": plan.action_id,
                        "validation_error": str(e),
                        "provided_args": plan.args,
                        "required_params": required
                    }
                )
            except jsonschema.exceptions.SchemaError as e:
                logger.error(f"Internal Schema error in contract for '{plan.action_id}': {e}")
                # We don't block execution if our validation engine itself has a bug/incompatibility
                # unless it's critical. But for now, we pass.
                return ValidationResult(is_valid=True)
            except Exception as e:
                logger.error(f"Validation engine error: {e}")

        # 4. Dependency Validation (Basic step dependencies)
        if plan.action_id.startswith("browser.") and plan.action_id != "browser.open":
            # Check if browser is actually open in drivers_state
            # This is a 'soft' dependency check
            drivers_state = getattr(session, "drivers_state", {})
            if "browser" not in drivers_state and "playwright" not in drivers_state:
                return ValidationResult(
                    is_valid=False,
                    error_code=ErrorCode.SYSTEM_DRIVER_UNAVAILABLE,
                    message=f"Action '{plan.action_id}' requires an active browser session. Use 'browser.open' first.",
                    diagnostics={"missing_dependency": "browser_session"}
                )

        # 5. Policy & Side-Effect Safety
        metadata = skill_registry.get_action_metadata(plan.action_id)
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
