"""Tool registry for managing and retrieving agent tools."""

from typing import Any

from forgeai.tools.base import BaseTool
from forgeai.tools.errors import ToolRegistrationError


class ToolRegistry:
    """A registry for managing available tools."""

    def __init__(self) -> None:
        """Initialize an empty tool registry."""
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        Register a tool.

        Args:
            tool: The tool instance to register.

        Raises:
            ToolRegistrationError: If a tool with the same name is already registered.
        """
        name = tool.definition.name
        if name in self._tools:
            raise ToolRegistrationError(f"Tool '{name}' is already registered.")
        self._tools[name] = tool

    def unregister(self, name: str) -> None:
        """
        Unregister a tool by name.

        Args:
            name: The name of the tool to remove.

        Raises:
            ToolRegistrationError: If the tool is not registered.
        """
        if name not in self._tools:
            raise ToolRegistrationError(f"Tool '{name}' is not registered.")
        del self._tools[name]

    def get(self, name: str) -> BaseTool:
        """
        Retrieve a tool by name.

        Args:
            name: The tool name.

        Returns:
            The requested BaseTool.

        Raises:
            ToolRegistrationError: If the tool is not found.
        """
        if name not in self._tools:
            raise ToolRegistrationError(f"Tool '{name}' is not registered.")
        return self._tools[name]

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        """
        Generate OpenAI-compatible tool schemas for all registered tools.

        Returns:
            A list of dictionary schemas compatible with OpenAI's 'tools' parameter.
        """
        schemas = []
        for tool in self._tools.values():
            definition = tool.definition
            schema = {
                "type": "function",
                "function": {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": definition.input_schema,
                },
            }
            schemas.append(schema)
        return schemas
