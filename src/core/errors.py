from enum import Enum
from typing import Optional, Any, Dict

class ErrorCode(str, Enum):
    # Planner Errors
    PLANNER_INVALID_JSON = "PLANNER_INVALID_JSON"
    PLANNER_SCHEMA_MISMATCH = "PLANNER_SCHEMA_MISMATCH"
    PLANNER_LOOP_DETECTED = "PLANNER_LOOP_DETECTED"
    
    # Tool/Skill Errors
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_PERMISSION_DENIED = "TOOL_PERMISSION_DENIED"
    
    # System/Network Errors
    NETWORK_FAILURE = "NETWORK_FAILURE"
    SYSTEM_DRIVER_UNAVAILABLE = "SYSTEM_DRIVER_UNAVAILABLE"
    SESSION_LOCKED = "SESSION_LOCKED"
    
    # Unknown
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

class AgentError(Exception):
    def __init__(
        self, 
        message: str, 
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR, 
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.code.value,
            "message": self.message,
            "details": self.details
        }
