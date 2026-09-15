"""Docker-based implementation of the sandbox."""

import os
import time
import uuid
from pathlib import Path

from forgeai.execution.runner import ProcessRunner
from forgeai.sandbox.errors import (
    SandboxCleanupError,
    SandboxConfigurationError,
    SandboxCreationError,
    SandboxExecutionError,
    SandboxUnavailableError,
)
from forgeai.sandbox.interface import Sandbox, SandboxManager
from forgeai.sandbox.models import CommandRequest, CommandResult, SandboxConfig


class DockerSandbox(Sandbox):
    """A Docker container functioning as an isolated sandbox."""

    def __init__(self, container_id: str, config: SandboxConfig) -> None:
        self.container_id = container_id
        self.config = config

    async def execute(self, request: CommandRequest) -> CommandResult:
        """Execute a command via 'docker exec'."""
        if not request.command:
            raise SandboxExecutionError("Command cannot be empty.")

        timeout = request.timeout_seconds or self.config.timeout_seconds

        args = ["docker", "exec"]
        if request.working_directory:
            args.extend(["-w", request.working_directory])

        # In non-interactive scripts we might just pass the command directly
        args.append(self.container_id)
        args.extend(request.command)

        try:
            result = await ProcessRunner.run(
                command=args,
                timeout=timeout,
                max_output_bytes=self.config.max_output_bytes,
            )
        except Exception as e:
            raise SandboxExecutionError(f"Failed to start docker exec: {e}") from e

        return CommandResult(
            exit_code=result.exit_code,
            stdout=result.stdout.decode("utf-8", errors="replace"),
            stderr=result.stderr.decode("utf-8", errors="replace"),
            duration_seconds=result.duration_seconds,
            timed_out=result.timed_out,
            success=result.exit_code == 0 and not result.timed_out,
            truncated=result.truncated,
        )

    async def destroy(self) -> None:
        """Force remove the Docker container."""
        try:
            await ProcessRunner.run(["docker", "rm", "-f", self.container_id])
        except Exception as e:
            raise SandboxCleanupError(
                f"Failed to destroy container {self.container_id}: {e}"
            ) from e


class DockerSandboxManager(SandboxManager):
    """Manages Docker-based sandboxes using the local docker CLI."""

    async def _check_availability(self) -> None:
        """Check if docker is available and responsive."""
        try:
            result = await ProcessRunner.run(["docker", "info"])
            if result.exit_code != 0:
                raise SandboxUnavailableError(
                    "Docker daemon is not running or accessible."
                )
        except FileNotFoundError:
            raise SandboxUnavailableError("Docker CLI not found on PATH.")
        except Exception as e:
            if isinstance(e, SandboxUnavailableError):
                raise
            raise SandboxUnavailableError(f"Error checking docker: {e}") from e

    async def create_sandbox(
        self, config: SandboxConfig, workspace_root: Path
    ) -> Sandbox:
        """Create and start a new container that sleeps indefinitely."""
        await self._check_availability()

        if not workspace_root.is_absolute():
            raise SandboxConfigurationError("Workspace root must be an absolute path.")
        if not workspace_root.is_dir():
            raise SandboxConfigurationError(
                f"Workspace root {workspace_root} does not exist or is not a directory."
            )

        # Generate a unique container name
        container_name = f"forgeai-sandbox-{uuid.uuid4().hex[:8]}"

        args = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--cpus",
            str(config.cpu_limit),
            "--memory",
            f"{config.memory_limit_mb}m",
            "-v",
            f"{workspace_root}:{config.working_directory}",
            "-w",
            config.working_directory,
        ]

        if not config.network_enabled:
            args.extend(["--network", "none"])

        if config.non_root_user:
            # Attempt to use host UID/GID on POSIX systems
            if hasattr(os, "getuid") and hasattr(os, "getgid"):
                uid = getattr(os, "getuid")()
                gid = getattr(os, "getgid")()
                args.extend(["--user", f"{uid}:{gid}"])
            else:
                args.extend(["--user", "1000:1000"])

        args.append(config.image)
        # Sleep indefinitely so we can exec into it
        args.extend(["sleep", "infinity"])

        try:
            result = await ProcessRunner.run(args)
            out = result.stdout
            err = result.stderr
            returncode = result.exit_code
        except Exception as e:
            raise SandboxCreationError(f"Failed to execute docker run: {e}") from e

        if returncode != 0:
            err_str = err.decode("utf-8", errors="replace").strip()
            raise SandboxCreationError(f"Docker container creation failed: {err_str}")

        container_id = out.decode("utf-8").strip()

        return DockerSandbox(container_id=container_id, config=config)
