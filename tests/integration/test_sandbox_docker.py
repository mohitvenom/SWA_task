"""Integration tests for the docker sandbox, using the real Docker daemon."""

import asyncio
from pathlib import Path

import pytest

from forgeai.sandbox.docker import DockerSandboxManager
from forgeai.sandbox.models import CommandRequest, SandboxConfig


async def docker_available() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "info",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0
    except Exception:
        return False


# Skip all tests in this file if Docker is not available
pytestmark = pytest.mark.skipif(
    not asyncio.run(docker_available()), reason="Docker is not available"
)


@pytest.fixture
def manager() -> DockerSandboxManager:
    return DockerSandboxManager()


@pytest.mark.anyio
async def test_real_docker_sandbox_lifecycle(
    manager: DockerSandboxManager, tmp_path: Path
) -> None:
    # 1. Create a dummy file in the workspace
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello from host")

    config = SandboxConfig(
        network_enabled=False,
        timeout_seconds=5,
    )

    # 2. Create sandbox
    sandbox = await manager.create_sandbox(config, tmp_path)

    try:
        # 3. Execute command to read the file
        req1 = CommandRequest(command=["cat", "/workspace/test.txt"])
        res1 = await sandbox.execute(req1)

        assert res1.success is True
        assert res1.exit_code == 0
        assert res1.stdout.strip() == "hello from host"

        # 4. Execute command that fails
        req2 = CommandRequest(command=["ls", "/nonexistent"])
        res2 = await sandbox.execute(req2)

        assert res2.success is False
        assert res2.exit_code != 0
        assert "No such file or directory" in res2.stderr

        # 5. Execute command that times out
        req3 = CommandRequest(command=["sleep", "10"], timeout_seconds=1)
        res3 = await sandbox.execute(req3)

        assert res3.success is False
        assert res3.timed_out is True

        # 6. Ensure network is disabled (should fail to reach external IP)
        req4 = CommandRequest(command=["ping", "-c", "1", "8.8.8.8"])
        res4 = await sandbox.execute(req4)

        assert res4.success is False

    finally:
        # 7. Destroy
        await sandbox.destroy()

        # Verify it's destroyed
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            getattr(sandbox, "container_id", ""),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        assert proc.returncode != 0


@pytest.mark.anyio
async def test_real_docker_sandbox_output_truncation(
    manager: DockerSandboxManager, tmp_path: Path
) -> None:
    config = SandboxConfig(max_output_bytes=10)
    sandbox = await manager.create_sandbox(config, tmp_path)

    try:
        req = CommandRequest(command=["echo", "12345678901234567890"])
        res = await sandbox.execute(req)

        assert res.success is True
        assert res.truncated is True
        assert len(res.stdout) == 10
        assert res.stdout == "1234567890"
    finally:
        await sandbox.destroy()
