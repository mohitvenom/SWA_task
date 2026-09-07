"""Domain errors for the tool system."""


class ToolError(Exception):
    """Base exception for all tool-related errors."""

    pass


class ToolRegistrationError(ToolError):
    """Raised when failing to register or retrieve a tool."""

    pass


class ToolExecutionError(ToolError):
    """Raised when a tool fails during execution."""

    pass


class SecurityViolationError(ToolError):
    """Raised when a tool attempts a forbidden action (e.g., path traversal)."""

    pass


class PathTraversalError(SecurityViolationError):
    """Raised when a path escapes the workspace root."""

    pass
