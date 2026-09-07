"""Domain models for sandbox execution."""

from enum import Enum

from pydantic import BaseModel, Field

from forgeai.config.settings import settings


class SandboxStatus(str, Enum):
    """The current status of a sandbox."""

    CREATED = "CREATED"
    INITIALIZED = "INITIALIZED"
    EXECUTING = "EXECUTING"
    DESTROYED = "DESTROYED"
    FAILED = "FAILED"


class SandboxConfig(BaseModel):
    """Configuration for a sandbox."""

    image: str = Field(default_factory=lambda: settings.sandbox_image)
    cpu_limit: float = Field(default_factory=lambda: settings.sandbox_cpu_limit)
    memory_limit_mb: int = Field(
        default_factory=lambda: settings.sandbox_memory_limit_mb
    )
    timeout_seconds: int = Field(
        default_factory=lambda: settings.sandbox_timeout_seconds
    )
    network_enabled: bool = Field(
        default_factory=lambda: settings.sandbox_network_enabled
    )
    working_directory: str = "/workspace"
    non_root_user: bool = True
    max_output_bytes: int = Field(
        default_factory=lambda: settings.sandbox_max_output_bytes
    )


class CommandRequest(BaseModel):
    """A command to execute inside a sandbox."""

    command: list[str]
    working_directory: str | None = None
    timeout_seconds: float | None = None


class CommandResult(BaseModel):
    """The result of executing a command inside a sandbox."""

    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    success: bool
    truncated: bool = False
