from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from core.errors import AgentSemanticError, ErrorCode, SyntaxError as AgentSyntaxError, TransportError


@dataclass
class ClassifiedError:
    error_type: str
    error_code: ErrorCode
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


class ErrorClassifier:
    TRANSPORT_HINTS = ("timeout", "timed out", "rate limit", "429", "auth", "unauthorized", "forbidden", "unavailable", "network")
    SYNTAX_HINTS = ("json", "parse", "malformed", "truncated", "schema", "contract")
    SEMANTIC_HINTS = ("action", "allowed", "capability", "params", "missing required", "invalid action")

    def classify(self, error: Exception, raw_output: Any = None) -> ClassifiedError:
        text = str(error or "").lower()
        if isinstance(error, TransportError) or any(hint in text for hint in self.TRANSPORT_HINTS):
            return ClassifiedError("TransportError", ErrorCode.NETWORK_FAILURE, str(error), {"raw_output": raw_output})
        if isinstance(error, AgentSyntaxError) or any(hint in text for hint in self.SYNTAX_HINTS):
            return ClassifiedError("SyntaxError", ErrorCode.PLANNER_INVALID_JSON, str(error), {"raw_output": raw_output})
        if isinstance(error, AgentSemanticError) or any(hint in text for hint in self.SEMANTIC_HINTS):
            return ClassifiedError("AgentSemanticError", ErrorCode.PLAN_VALIDATION_FAILED, str(error), {"raw_output": raw_output})
        return ClassifiedError("TransportError", ErrorCode.UNKNOWN_ERROR, str(error), {"raw_output": raw_output})

