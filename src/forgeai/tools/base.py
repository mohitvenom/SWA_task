"""Base protocol and classes for tools."""

from abc import ABC, abstractmethod

from forgeai.tools.models import ToolCall, ToolContext, ToolDefinition, ToolResult


class BaseTool(ABC):
    """Abstract base class for all tools."""

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """Return the schema and metadata defining this tool."""
        pass

    @abstractmethod
    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        """
        Execute the tool with the given call arguments and context.

        Args:
            call: The specific tool invocation.
            context: The execution environment (workspace root, session, etc.).

        Returns:
            The result of the tool execution.
        """
        pass
