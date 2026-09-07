"""Sandbox interfaces."""

from pathlib import Path
from typing import Protocol

from forgeai.sandbox.models import CommandRequest, CommandResult, SandboxConfig


class Sandbox(Protocol):
    """An isolated execution environment."""

    async def execute(self, request: CommandRequest) -> CommandResult:
        """
        Execute a command inside the sandbox.

        Args:
            request: The command execution request.

        Returns:
            The result of the command execution.
        """
        ...

    async def destroy(self) -> None:
        """
        Tear down the sandbox and clean up resources.
        """
        ...


class SandboxManager(Protocol):
    """Manages the lifecycle of sandboxes."""

    async def create_sandbox(
        self, config: SandboxConfig, workspace_root: Path
    ) -> Sandbox:
        """
        Create and initialize a new sandbox.

        Args:
            config: The sandbox configuration.
            workspace_root: The host directory to mount into the sandbox.

        Returns:
            An initialized Sandbox ready for execution.
        """
        ...
