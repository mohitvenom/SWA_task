"""Run command execution tool backed by the sandbox."""

from typing import Any

from pydantic import ValidationError

from forgeai.sandbox.interface import SandboxManager
from forgeai.sandbox.models import CommandRequest, SandboxConfig
from forgeai.tools.base import BaseTool
from forgeai.tools.errors import SecurityViolationError, ToolExecutionError
from forgeai.tools.models import (
    ToolCall,
    ToolCapability,
    ToolContext,
    ToolDefinition,
    ToolResult,
)


class RunCommandTool(BaseTool):
    """A tool to safely run validation commands inside the Sandbox."""

    ALLOWED_COMMANDS = {
        "pytest",
        "python",
        "ruff",
        "mypy",
    }

    def __init__(self, sandbox_manager: SandboxManager) -> None:
        """
        Initialize the RunCommandTool.

        Args:
            sandbox_manager: The sandbox manager to execute commands.
        """
        self._sandbox_manager = sandbox_manager

    @property
    def definition(self) -> ToolDefinition:
        """Get the tool definition."""
        return ToolDefinition(
            name="run_command",
            description="Run a validation command inside the secure sandbox.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The command and arguments to execute (e.g., ['pytest', '-v']).",
                    },
                },
                "required": ["command"],
            },
            capability=ToolCapability.EXECUTION,
            is_dangerous=False,
        )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        """
        Execute the tool.

        Args:
            call: The tool call request.
            context: The execution context.

        Returns:
            The tool execution result.
        """
        try:
            raw_command = call.arguments.get("command")
            if not isinstance(raw_command, list) or not raw_command:
                raise ValueError("Command must be a non-empty list of strings.")

            command = [str(arg) for arg in raw_command]

            # Enforce command policy
            base_cmd = command[0].lower()
            if base_cmd not in self.ALLOWED_COMMANDS:
                raise SecurityViolationError(
                    f"Command '{base_cmd}' is not allowed. Only safe validation "
                    f"commands are permitted: {sorted(list(self.ALLOWED_COMMANDS))}."
                )

            # Prevent running python scripts directly outside tests
            if base_cmd == "python":
                if len(command) > 1 and command[1] != "-m":
                    raise SecurityViolationError(
                        "Arbitrary python scripts cannot be executed. Use 'python -m <module>'."
                    )
                if len(command) > 2 and command[2] not in {"pytest"}:
                    raise SecurityViolationError(
                        f"Python module '{command[2]}' is not allowed."
                    )

            sandbox_config = SandboxConfig()
            sandbox = await self._sandbox_manager.create_sandbox(
                sandbox_config, context.workspace_root
            )

            try:
                request = CommandRequest(command=command)
                result = await sandbox.execute(request)

                output = {
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "success": result.success,
                    "timed_out": result.timed_out,
                    "truncated": result.truncated,
                }

                return ToolResult(
                    call_id=call.call_id,
                    success=result.success,
                    output=output,
                )

            finally:
                await sandbox.destroy()

        except SecurityViolationError as e:
            raise e
        except Exception as e:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=str(e),
            )
