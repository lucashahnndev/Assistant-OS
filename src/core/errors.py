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
    TOOL_INVALID_INPUT = "TOOL_INVALID_INPUT"
    TOOL_RATE_LIMITED = "TOOL_RATE_LIMITED"
    
    # System/Network Errors
    NETWORK_FAILURE = "NETWORK_FAILURE"
    SYSTEM_DRIVER_UNAVAILABLE = "SYSTEM_DRIVER_UNAVAILABLE"
    SESSION_LOCKED = "SESSION_LOCKED"
    STREAMS_INTERRUPTED = "STREAMS_INTERRUPTED"
    
    # Execution Errors
    EXECUTION_STUCK = "EXECUTION_STUCK"
    EXECUTION_INTERRUPTED = "EXECUTION_INTERRUPTED"
    
    # Policy & Request Errors
    INVALID_REQUEST = "INVALID_REQUEST"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    
    PLAN_VALIDATION_FAILED = "PLAN_VALIDATION_FAILED"
    RECOVERY_NEEDED = "RECOVERY_NEEDED"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    
    # Unknown
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

class ErrorCategory(str, Enum):
    TRANSIENT = "TRANSIENT"      # Network, timeouts, rate limits (Retryable)
    FATAL = "FATAL"              # Invalid signatures, logic errors (Non-retryable)
    PERMISSION = "PERMISSION"    # Access denied, auth missing (User action)
    DEPENDENCY = "DEPENDENCY"    # Tool missing, driver fails
    STALLED = "STALLED"          # Process alive but zero progress

class AgentError(Exception):
    def __init__(
        self, 
        message: str, 
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR, 
        details: Optional[Dict[str, Any]] = None,
        category: Optional[ErrorCategory] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.category = category or self._infer_category(code)

    def _infer_category(self, code: ErrorCode) -> ErrorCategory:
        if code in [ErrorCode.NETWORK_FAILURE, ErrorCode.TOOL_TIMEOUT, ErrorCode.TOOL_RATE_LIMITED]:
            return ErrorCategory.TRANSIENT
        if code in [ErrorCode.TOOL_PERMISSION_DENIED, ErrorCode.POLICY_BLOCKED]:
            return ErrorCategory.PERMISSION
        if code in [ErrorCode.TOOL_NOT_FOUND, ErrorCode.SYSTEM_DRIVER_UNAVAILABLE]:
            return ErrorCategory.DEPENDENCY
        if code == ErrorCode.EXECUTION_STUCK:
            return ErrorCategory.STALLED
        if code == ErrorCode.INVALID_REQUEST:
            return ErrorCategory.FATAL
        return ErrorCategory.FATAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.code.value,
            "category": self.category.value,
            "message": self.message,
            "details": self.details
        }
