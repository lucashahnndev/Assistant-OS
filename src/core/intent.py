import json
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class AgentIntent(BaseModel):
    """
    Represents the structured intent returned by the LLM.
    The LLM does not execute code; it returns this intent.
    The Agent Core is responsible for executing the action.
    """
    
    thought: str = Field(..., description="The reasoning process of the LLM before deciding the action.")
    plan: list[str] = Field(default_factory=list, description="A persistent list of steps to complete the task. Update this as you progress.")
    state_summary: Dict[str, Any] = Field(default_factory=dict, description="Internal state in TOON format to be carried over to the next turn.")
    action: str = Field(..., description="The name of the action to be executed (e.g., 'play_music', 'search_web').")
    params: Dict[str, Any] = Field(default_factory=dict, description="Parameters required for the action.")
    task_label: Optional[str] = Field(None, description="A short, human-readable label for the task (e.g., 'Capturing screen', 'Searching on Google').")
    response_text: Optional[str] = Field(None, description="Text to be spoken back to the user immediately.")
    attachments: Optional[List[str]] = Field(None, description="A list of absolute file paths to attach to the response when action is 'reply'.")

    def to_json(self) -> str:
        return self.model_dump_json()

    def to_history_str(self) -> str:
        """Returns a JSON string for history tracking to reinforce the pattern."""
        return self.model_dump_json()
