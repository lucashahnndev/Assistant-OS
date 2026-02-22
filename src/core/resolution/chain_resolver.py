from typing import List, Optional, Dict, Any
from .base import IntentResolver
from .action_plan import ActionPlan
import logging

logger = logging.getLogger("FallbackChainResolver")

class FallbackChainResolver(IntentResolver):
    def __init__(self, resolvers: List[IntentResolver]):
        self.resolvers = resolvers

    def resolve(self, user_input: str, context: Dict[str, Any]) -> Optional[ActionPlan]:
        for resolver in self.resolvers:
            try:
                plan = resolver.resolve(user_input, context)
                if plan:
                    logger.info(f"Resolved intent using {resolver.__class__.__name__} | Action: {plan.action_id} | Confidence: {plan.confidence}")
                    return plan
            except Exception as e:
                logger.error(f"Error in {resolver.__class__.__name__}: {e}")
                continue
        return None
