from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

@dataclass
class ActionPlan:
    action_id: str
    args: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    source: str = "unknown" # "llm" | "semantic" | "reflex"
    response_text: Optional[str] = None
    thought: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    attachments: Optional[List[str]] = None

    def to_dict(self):
        return {
            "action_id": self.action_id,
            "args": self.args,
            "confidence": self.confidence,
            "source": self.source,
            "response_text": self.response_text,
            "thought": self.thought,
            "metadata": self.metadata,
            "attachments": self.attachments
        }
