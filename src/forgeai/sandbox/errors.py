"""Exceptions for sandbox execution."""


class SandboxError(Exception):
    """Base exception for all sandbox-related errors."""

    pass


class SandboxConfigurationError(SandboxError):
    """Raised when sandbox configuration is invalid."""

    pass


class SandboxUnavailableError(SandboxError):
    """Raised when sandbox provider (e.g., Docker) is not available."""

    pass


class SandboxCreationError(SandboxError):
    """Raised when sandbox creation fails."""

    pass


class SandboxExecutionError(SandboxError):
    """Raised when an internal error occurs during command execution."""

    pass


class SandboxTimeoutError(SandboxError):
    """Raised when an operation times out (not the command itself, but sandbox ops)."""

    pass


class SandboxCleanupError(SandboxError):
    """Raised when sandbox cleanup fails."""

    pass
