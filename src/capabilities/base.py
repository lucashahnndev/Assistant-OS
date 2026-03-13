from abc import ABC, abstractmethod
from typing import Dict, Any, List
import re

class CapabilityBase(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def actions(self) -> List[str]:
        """Returns a list of action IDs this capability can handle."""
        pass

    @abstractmethod
    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes the capability action and returns a structured dictionary.
        
        CANONICAL RESULT SHAPE:
        {
            "ok": bool,
            "status": "success" | "error" | "empty",
            "provider": str,
            "data": Dict[str, Any],       # Technical payload
            "metadata": Dict[str, Any]    # Optional technical metadata
        }
        
        CRITICAL: Conversational fields (text, message, reply, legacy_text, etc.) are FORBIDDEN.
        Capabilities must only return technical signals/data.
        """
        pass

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        """Optional: returns a list of reflex rules {pattern, action_id, handler}."""
        return []

    def get_documentation(self) -> str:
        """Returns the documentation for the LLM."""
        return ""
