"""Docker-based implementation of the sandbox."""

import asyncio
import os
import time
import uuid
from pathlib import Path

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

    async def _read_stream(
        self, stream: asyncio.StreamReader, limit: int
    ) -> tuple[bytes, bool]:
        """Read a stream up to the byte limit. Return (data, truncated)."""
        data = bytearray()
        truncated = False
        try:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                if len(data) + len(chunk) > limit:
                    data.extend(chunk[: limit - len(data)])
                    truncated = True
                    break
                data.extend(chunk)
        except Exception:
            pass
        return bytes(data), truncated

    async def execute(self, request: CommandRequest) -> CommandResult:
        """Execute a command via 'docker exec'."""
        if not request.command:
            raise SandboxExecutionError("Command cannot be empty.")

        timeout = request.timeout_seconds or self.config.timeout_seconds

        args = ["docker", "exec", "-i"]
        if request.working_directory:
            args.extend(["-w", request.working_directory])

        # In non-interactive scripts we might just pass the command directly
        args.append(self.container_id)
        args.extend(request.command)

        start_time = time.monotonic()

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )
        except Exception as e:
            raise SandboxExecutionError(f"Failed to start docker exec: {e}") from e

        assert process.stdout is not None
        assert process.stderr is not None

        timed_out = False
        try:
            # We wait for the process with a timeout, reading streams concurrently
            stdout_task = asyncio.create_task(
                self._read_stream(process.stdout, self.config.max_output_bytes)
            )
            stderr_task = asyncio.create_task(
                self._read_stream(process.stderr, self.config.max_output_bytes)
            )

            await asyncio.wait_for(process.wait(), timeout=timeout)

            out, out_truncated = await stdout_task
            err, err_truncated = await stderr_task

        except asyncio.TimeoutError:
            timed_out = True
            try:
                process.kill()
            except ProcessLookupError:
                pass

            out, out_truncated = await stdout_task
            err, err_truncated = await stderr_task

        duration = time.monotonic() - start_time

        return CommandResult(
            exit_code=process.returncode if not timed_out else None,
            stdout=out.decode("utf-8", errors="replace"),
            stderr=err.decode("utf-8", errors="replace"),
            duration_seconds=duration,
            timed_out=timed_out,
            success=process.returncode == 0 and not timed_out,
            truncated=out_truncated or err_truncated,
        )

    async def destroy(self) -> None:
        """Force remove the Docker container."""
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "rm",
                "-f",
                self.container_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
        except Exception as e:
            raise SandboxCleanupError(
                f"Failed to destroy container {self.container_id}: {e}"
            ) from e


class DockerSandboxManager(SandboxManager):
    """Manages Docker-based sandboxes using the local docker CLI."""

    async def _check_availability(self) -> None:
        """Check if docker is available and responsive."""
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.wait()
            if process.returncode != 0:
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
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await process.communicate()
        except Exception as e:
            raise SandboxCreationError(f"Failed to execute docker run: {e}") from e

        if process.returncode != 0:
            err_str = err.decode("utf-8", errors="replace").strip()
            raise SandboxCreationError(f"Docker container creation failed: {err_str}")

        container_id = out.decode("utf-8").strip()

        return DockerSandbox(container_id=container_id, config=config)
