"""Process runner for controlled, async-safe subprocess execution."""

import subprocess
import time
from typing import Optional, Sequence

import anyio


class ProcessResult:
    """Result of a process execution."""

    def __init__(
        self,
        exit_code: Optional[int],
        stdout: bytes,
        stderr: bytes,
        timed_out: bool,
        truncated: bool,
        duration_seconds: float,
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.truncated = truncated
        self.duration_seconds = duration_seconds


class ProcessRunner:
    """A framework-agnostic process runner utilizing AnyIO."""

    @staticmethod
    async def run(
        command: Sequence[str],
        cwd: str | None = None,
        timeout: float | None = None,
        max_output_bytes: int = 10 * 1024 * 1024,
    ) -> ProcessResult:
        """
        Execute a command in a subprocess safely.

        Args:
            command: The command and its arguments.
            cwd: The working directory for the command.
            timeout: Maximum execution time in seconds.
            max_output_bytes: Maximum size of captured output before truncating.

        Returns:
            A ProcessResult object detailing the execution outcome.
        """
        start_time = time.monotonic()
        timed_out = False
        truncated = False
        stdout_chunks = bytearray()
        stderr_chunks = bytearray()

        async def read_stream(stream: anyio.abc.ByteReceiveStream, chunks_list: bytearray) -> None:
            nonlocal truncated
            try:
                async for chunk in stream:
                    remaining = max_output_bytes - len(chunks_list)
                    if len(chunk) > remaining:
                        chunks_list.extend(chunk[:remaining])
                        truncated = True
                        break
                    else:
                        chunks_list.extend(chunk)
            except Exception:
                # Ignore stream read errors to prevent them from crashing the runner
                pass

        exit_code = None

        try:
            # anyio.fail_after handles the timeout gracefully by cancelling the process
            with anyio.fail_after(timeout) if timeout is not None else anyio.CancelScope():
                async with await anyio.open_process(
                    command,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                ) as process:
                    async with anyio.create_task_group() as tg:
                        if process.stdout:
                            tg.start_soon(read_stream, process.stdout, stdout_chunks)
                        if process.stderr:
                            tg.start_soon(read_stream, process.stderr, stderr_chunks)

                    await process.wait()
                    exit_code = process.returncode
        except TimeoutError:
            timed_out = True
        except Exception as e:
            # We let unexpected exceptions bubble up, but not timeouts.
            raise e

        duration = time.monotonic() - start_time
        return ProcessResult(
            exit_code=exit_code,
            stdout=bytes(stdout_chunks),
            stderr=bytes(stderr_chunks),
            timed_out=timed_out,
            truncated=truncated,
            duration_seconds=duration,
        )
