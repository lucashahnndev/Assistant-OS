import logging
from typing import Any, Dict, List, Optional

from core.action_gateway import ActionGateway
from ..base import CapabilityBase

logger = logging.getLogger("ReflexCapability")


class ReflexCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "reflex"

    @property
    def name(self) -> str:
        return "reflex_system"

    @property
    def actions(self) -> List[str]:
        return ["status", "cancel"]

    @staticmethod
    def _result(ok: bool, status: str, error_details: str = "", **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": ok, "status": status, "error_details": error_details}
        payload.update(extra)
        return payload

    def _resolve_registry(self, context: Dict[str, Any]) -> Optional[Any]:
        kernel = self.kernel or context.get("kernel")
        if not kernel:
            return None
        registry = getattr(kernel, "capability_registry", None)
        if registry:
            return registry
        orchestrator = getattr(kernel, "orchestrator", None)
        return getattr(orchestrator, "capability_registry", None) if orchestrator else None

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
        if not registry.get_capability_for_action(target_action):
            return None
        gateway = ActionGateway()
        return gateway.execute_action(
            action_id=target_action,
            params=params,
            allowed_actions=registry.list_actions() if hasattr(registry, "list_actions") else [target_action],
            capability_registry=registry,
            capability_metadata=(
                registry.get_action_metadata(target_action)
                if hasattr(registry, "get_action_metadata")
                else {}
            ),
            context=context,
            strict_mode=False,
        )

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        delegated = self._delegate_to_system_control(action_id, params, context)
        if delegated is not None:
            return delegated

        return self._result(
            ok=False,
            status="error",
            error_details=f"Unable to dispatch reflex action: {action_id}",
            error_code="CAPABILITY_DISPATCH_UNAVAILABLE",
        )

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        return []
