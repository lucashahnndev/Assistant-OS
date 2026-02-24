from typing import Optional, Dict, Any
from core.resolution.base import IntentResolver
from core.resolution.action_plan import ActionPlan
from .registry import ReflexRegistry
import logging

logger = logging.getLogger("ReflexResolver")

class ReflexResolver(IntentResolver):
    def __init__(self, registry: ReflexRegistry):
        self.registry = registry

    def resolve(self, user_input: str, context: Dict[str, Any]) -> Optional[ActionPlan]:
        plan = self.registry.match(user_input)
        if plan:
            logger.info(f"Reflex matched: {plan.action_id}")
            return plan
        return None
