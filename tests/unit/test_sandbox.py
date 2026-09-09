"""Unit tests for the docker sandbox, mocking the subprocess calls."""

import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forgeai.execution.runner import ProcessResult
from forgeai.sandbox.docker import DockerSandbox, DockerSandboxManager
from forgeai.sandbox.errors import (
    SandboxConfigurationError,
    SandboxCreationError,
    SandboxUnavailableError,
)
from forgeai.sandbox.models import CommandRequest, SandboxConfig


@pytest.fixture
def mock_subprocess() -> Any:  # type: ignore
    with patch("forgeai.sandbox.docker.ProcessRunner.run", new_callable=AsyncMock) as mock_exec:
        yield mock_exec


def create_mock_process(
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    timed_out: bool = False,
    truncated: bool = False,
) -> ProcessResult:
    return ProcessResult(
        exit_code=returncode if not timed_out else None,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        truncated=truncated,
        duration_seconds=0.1,
    )


@pytest.mark.anyio
async def test_manager_check_availability_success(mock_subprocess: MagicMock) -> None:
    mock_subprocess.return_value = create_mock_process(returncode=0)
    manager = DockerSandboxManager()
    await manager._check_availability()
    mock_subprocess.assert_called_with(["docker", "info"])


@pytest.mark.anyio
async def test_manager_check_availability_failure(mock_subprocess: MagicMock) -> None:
    mock_subprocess.return_value = create_mock_process(returncode=1)
    manager = DockerSandboxManager()
    with pytest.raises(SandboxUnavailableError, match="Docker daemon is not running"):
        await manager._check_availability()


@pytest.mark.anyio
async def test_manager_create_sandbox_success(
    mock_subprocess: MagicMock, tmp_path: Path
) -> None:
    # First call: docker info
    # Second call: docker run
    mock_info = create_mock_process(returncode=0)
    mock_run = create_mock_process(returncode=0, stdout=b"fake-container-id\n")
    mock_subprocess.side_effect = [mock_info, mock_run]

    manager = DockerSandboxManager()
    config = SandboxConfig(network_enabled=False)

    sandbox = await manager.create_sandbox(config, tmp_path)

    assert isinstance(sandbox, DockerSandbox)
    assert sandbox.container_id == "fake-container-id"

    # Verify docker run arguments
    args = mock_subprocess.call_args_list[1][0][0]
    assert "docker" in args
    assert "run" in args
    assert "-d" in args
    assert "--security-opt" in args
    assert "no-new-privileges" in args
    assert "--cap-drop" in args
    assert "ALL" in args
    assert "--network" in args
    assert "none" in args
    if hasattr(os, "getuid"):
        assert "--user" in args


@pytest.mark.anyio
async def test_manager_create_sandbox_invalid_path(tmp_path: Path) -> None:
    manager = DockerSandboxManager()
    manager._check_availability = AsyncMock()  # type: ignore

    with pytest.raises(SandboxConfigurationError, match="must be an absolute path"):
        await manager.create_sandbox(SandboxConfig(), Path("relative/path"))

    with pytest.raises(SandboxConfigurationError, match="does not exist"):
        await manager.create_sandbox(SandboxConfig(), tmp_path / "missing")


@pytest.mark.anyio
async def test_manager_create_sandbox_failure(
    mock_subprocess: MagicMock, tmp_path: Path
) -> None:
    mock_info = create_mock_process(returncode=0)
    mock_run = create_mock_process(returncode=1, stderr=b"Error starting container")
    mock_subprocess.side_effect = [mock_info, mock_run]

    manager = DockerSandboxManager()

    with pytest.raises(SandboxCreationError, match="Error starting container"):
        await manager.create_sandbox(SandboxConfig(), tmp_path)


@pytest.mark.anyio
async def test_sandbox_execute_success(mock_subprocess: MagicMock) -> None:
    mock_exec = create_mock_process(returncode=0, stdout=b"hello\n")
    mock_subprocess.return_value = mock_exec

    sandbox = DockerSandbox("test-id", SandboxConfig())
    req = CommandRequest(command=["echo", "hello"])

    result = await sandbox.execute(req)

    assert result.success is True
    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.truncated is False

    kwargs = mock_subprocess.call_args.kwargs
    assert kwargs["command"] == ["docker", "exec", "-i", "test-id", "echo", "hello"]


@pytest.mark.anyio
async def test_sandbox_execute_timeout(mock_subprocess: MagicMock) -> None:
    # ProcessRunner handles timeout internally, so we just mock it returning a timeout
    process = create_mock_process(stdout=b"partial", timed_out=True)
    mock_subprocess.return_value = process

    sandbox = DockerSandbox("test-id", SandboxConfig())
    req = CommandRequest(command=["sleep", "10"], timeout_seconds=0.1)

    result = await sandbox.execute(req)

    assert result.success is False
    assert result.timed_out is True
    assert result.exit_code is None
    assert result.stdout == "partial"


@pytest.mark.anyio
async def test_sandbox_execute_truncation(mock_subprocess: MagicMock) -> None:
    large_data = b"x" * 100
    process = create_mock_process(returncode=0, stdout=large_data, truncated=True)
    mock_subprocess.return_value = process

    config = SandboxConfig(max_output_bytes=100)
    sandbox = DockerSandbox("test-id", config)
    req = CommandRequest(command=["echo", "large"])

    result = await sandbox.execute(req)

    assert result.success is True
    assert result.truncated is True
    assert len(result.stdout) == 100
    assert result.stdout == "x" * 100


@pytest.mark.anyio
async def test_sandbox_destroy(mock_subprocess: MagicMock) -> None:
    mock_rm = create_mock_process(returncode=0)
    mock_subprocess.return_value = mock_rm

    sandbox = DockerSandbox("test-id", SandboxConfig())
    await sandbox.destroy()

    mock_subprocess.assert_called_with(["docker", "rm", "-f", "test-id"])
