from enum import Enum
from typing import Dict, Any, Optional

class ErrorCode(str, Enum):
    TIMEOUT = "TIMEOUT"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    INVALID_PLANNER_JSON = "INVALID_PLANNER_JSON"
    LOOP_DETECTED = "LOOP_DETECTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SKILL_NOT_FOUND = "SKILL_NOT_FOUND"

class AgentError(Exception):
    """
    Base exception for all agent-related failures.
    Supports structured error codes and optional metadata.
    """
    def __init__(self, message: str, code: ErrorCode = ErrorCode.INTERNAL_ERROR, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.message,
            "code": self.code.value,
            "details": self.details
        }
