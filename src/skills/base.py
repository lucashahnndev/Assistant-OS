from abc import ABC, abstractmethod
from typing import Dict, Any, List
import re

class SkillBase(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def actions(self) -> List[str]:
        """Returns a list of action IDs this skill can handle."""
        pass

    @abstractmethod
    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        pass

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        """Optional: returns a list of reflex rules {pattern, action_id, handler}."""
        return []

    def get_documentation(self) -> str:
        """Returns the documentation for the LLM."""
        return ""
