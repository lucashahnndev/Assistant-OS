import logging
from typing import Any, Dict, List, Optional

from ..base import SkillBase

logger = logging.getLogger("ReflexSkill")


class ReflexSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "reflex"

    @property
    def name(self) -> str:
        return "reflex_system"

    @property
    def actions(self) -> List[str]:
        # Backward-compatible aliases. Primary commands now live in system.control.*
        return ["status", "cancel"]

    @staticmethod
    def _result(ok: bool, status: str, error_details: str = "", **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": ok, "status": status, "error_details": text}
        payload.update(extra)
        return payload

    def _resolve_registry(self, context: Dict[str, Any]) -> Optional[Any]:
        kernel = self.kernel or context.get("kernel")
        if not kernel:
            return None
        registry = getattr(kernel, "skill_registry", None)
        if registry:
            return registry
        orchestrator = getattr(kernel, "orchestrator", None)
        return getattr(orchestrator, "skill_registry", None) if orchestrator else None

    def _delegate_to_system_control(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Optional[Any]:
        mapping = {
            "status": "system.control.status",
            "cancel": "system.control.cancel",
        }
        local = action_id.split(".")[-1]
        target_action = mapping.get(local)
        if not target_action:
            return None

        registry = self._resolve_registry(context)
        if not registry:
            return None
        if not registry.get_skill_for_action(target_action):
            return None
        return registry.dispatch(target_action, params, context)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        delegated = self._delegate_to_system_control(action_id, params, context)
        if delegated is not None:
            if isinstance(delegated, dict):
                delegated.setdefault("legacy_alias", "reflex")
                return delegated
            return self._result(
                ok=True,
                status="success",
                error_details=str(delegated),
                legacy_alias="reflex",
                delegated_action=action_id,
                result=delegated,
            )

        action = action_id.split(".")[-1]
        if action == "status":
            return self._result(
                ok=False,
                status="error",
                error_details="Ação reflex.status descontinuada. Use system.control.status.",
                error="DEPRECATED_ACTION",
                replacement="system.control.status",
            )
        if action == "cancel":
            return self._result(
                ok=False,
                status="error",
                error_details="Ação reflex.cancel descontinuada. Use system.control.cancel.",
                error="DEPRECATED_ACTION",
                replacement="system.control.cancel",
            )
        return self._result(
            ok=False,
            status="error",
            error_details=f"Unknown reflex action: {action_id}",
            error="UNKNOWN_ACTION",
        )

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        # Rules moved to system_control to avoid duplicate command surfaces.
        return []
