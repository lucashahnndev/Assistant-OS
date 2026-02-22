from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from .action_plan import ActionPlan

class IntentResolver(ABC):
    @abstractmethod
    def resolve(self, user_input: str, context: Dict[str, Any]) -> Optional[ActionPlan]:
        """
        Resolves user input into an ActionPlan.
        Returns None if the resolver cannot handle the input.
        """
        pass
