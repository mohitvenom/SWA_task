"""Domain models for the tool system."""

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ToolCapability(str, Enum):
    """The capability classification of a tool."""

    READ_ONLY = "READ_ONLY"
    MUTATION = "MUTATION"
    EXECUTION = "EXECUTION"


class ToolDefinition(BaseModel):
    """Defines a tool's capabilities and schema."""

    name: str
    description: str
    input_schema: dict[str, Any]
    capability: ToolCapability = ToolCapability.READ_ONLY
    is_dangerous: bool = False
    timeout_seconds: int | None = None


class ToolCall(BaseModel):
    """A specific request to execute a tool."""

    call_id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    """The result of executing a tool."""

    call_id: str
    success: bool
    output: Any | None = None
    error: str | None = None


class ToolContext(BaseModel):
    """The execution context passed to tools."""

    workspace_root: Path
    session_id: str | None = None
