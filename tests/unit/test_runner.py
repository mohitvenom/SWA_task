import pytest
import sys
from unittest.mock import patch
from forgeai.execution.runner import ProcessRunner

@pytest.mark.anyio
async def test_process_runner_fallback_not_implemented():
    """
    Regression test for the ProcessRunner asyncio Windows fallback.
    Simulates a NotImplementedError raised by anyio.open_process (e.g., when 
    using SelectorEventLoop on Windows) and ensures the fallback executes.
    """
    # Mock anyio.open_process to raise NotImplementedError
    with patch("anyio.open_process", side_effect=NotImplementedError("Mock loop issue")):
        # The fallback uses subprocess.run. We can just execute a safe command like 'echo test' or 'python -c "print(1)"'
        cmd = [sys.executable, "-c", "print('hello fallback')"]
        result = await ProcessRunner.run(cmd)
        
        assert result.exit_code == 0
        assert b"hello fallback" in result.stdout
        assert result.timed_out is False
        assert result.truncated is False

@pytest.mark.anyio
async def test_process_runner_interactive_command_fails_fast():
    """
    Prove that an interactive command does not wait for the full timeout 
    and fails immediately because stdin is closed/DEVNULL.
    """
    import time
    cmd = [sys.executable, "-c", "input('Enter: ')"]
    start = time.monotonic()
    result = await ProcessRunner.run(cmd, timeout=5.0)
    duration = time.monotonic() - start
    
    assert duration < 2.0  # Should fail instantly, well before the 5s timeout
    assert result.exit_code != 0
    assert b"EOFError" in result.stderr
    assert result.timed_out is False

