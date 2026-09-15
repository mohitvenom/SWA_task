"""
Tests for the Fast Path simple task execution in ApplicationOrchestrator.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forgeai.agents.models import ExecutionResult, ExecutionStatus, TaskIntelligenceStatus, EngineeringTask, CodingResult, CodingPhase, CodingSession, TestStrategy
from forgeai.git.models import GitStatus, GitBranch, GitCommit, WorkspaceCheckpoint
from forgeai.orchestrator import ApplicationOrchestrator
from forgeai.tools.errors import SecurityViolationError
from forgeai.tools.models import ToolResult

from forgeai.config.settings import settings
from collections.abc import Generator

@pytest.fixture(autouse=True)
def _enable_autonomous_execution() -> Generator[None, None, None]:
    original = settings.autonomous_execution_enabled
    settings.autonomous_execution_enabled = True
    try:
        yield
    finally:
        settings.autonomous_execution_enabled = original

@pytest.fixture
def mock_git():
    git = MagicMock()
    git.get_status = AsyncMock(return_value=GitStatus(branch="main", is_clean=True, unstaged_changes=[], staged_changes=[], untracked_changes=[]))
    git.create_branch = AsyncMock(return_value=GitBranch(name="test-branch", is_current=True, is_remote=False))
    git.create_checkpoint = AsyncMock(return_value=WorkspaceCheckpoint(task_id="tid", commit_hash="1234abc", branch="test-branch", status=GitStatus(branch="main", is_clean=True, unstaged_changes=[], staged_changes=[], untracked_changes=[])))
    git.stage_files = AsyncMock()
    git.commit = AsyncMock(return_value=GitCommit(commit_hash="5678def", message="Test", branch="main"))
    git.restore_checkpoint = AsyncMock()
    return git


@pytest.fixture
def mock_tools():
    tools = MagicMock()
    
    mock_write = MagicMock()
    mock_write.execute = AsyncMock(return_value=ToolResult(call_id="call-123", success=True, output={}))
    
    tools.get.return_value = mock_write
    return tools


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def orchestrator(mock_llm, mock_tools, mock_git):
    return ApplicationOrchestrator(
        llm_client=mock_llm,
        tool_registry=mock_tools,
        git_service=mock_git,
    )


@pytest.mark.parametrize("request_text", [
    "Create hello.txt containing exactly: Hello from ForgeAI",
    "Create a file named hello.txt containing exactly: Hello from ForgeAI"
])
@pytest.mark.anyio
async def test_fast_path_simple_file_creation(orchestrator, mock_git, mock_tools, request_text):
    workspace = Path("/tmp/workspace")
    
    with patch("forgeai.orchestrator.TaskIntelligenceAgent") as MockTIAgent, \
         patch("forgeai.orchestrator.PlanningAgent") as MockPlanner, \
         patch("forgeai.orchestrator.TestStrategyAgent") as MockTestAgent, \
         patch("forgeai.orchestrator.ReviewAgent") as MockReviewer:
        
        result = await orchestrator.execute_task(request_text, workspace)
        
        assert result.status == ExecutionStatus.COMPLETED
        assert result.changed_files == ["hello.txt"]
        assert result.git_result == {"commit_hash": "5678def"}
        assert result.success is True
        
        # Verify agents were NOT invoked
        MockTIAgent.assert_not_called()
        MockPlanner.assert_not_called()
        MockTestAgent.assert_not_called()
        MockReviewer.assert_not_called()
        
        # Verify tool was called
        mock_tools.get.assert_called_with("write_file")
        tool_instance = mock_tools.get.return_value
        tool_instance.execute.assert_called_once()
        
        call_arg = tool_instance.execute.call_args[0][0]
        assert call_arg.arguments["path"] == "hello.txt"
        assert call_arg.arguments["content"] == "Hello from ForgeAI"


@pytest.mark.anyio
async def test_fast_path_unauthorized_path_rejected(orchestrator, mock_git, mock_tools):
    workspace = Path("/tmp/workspace")
    request = "Create ../outside.txt containing exactly: malicious"
    
    # Simulate the write tool raising a SecurityViolationError
    mock_write = mock_tools.get.return_value
    mock_write.execute.side_effect = SecurityViolationError("Path outside workspace")
    
    result = await orchestrator.execute_task(request, workspace)
    
    assert result.status == ExecutionStatus.SECURITY_REJECTED
    assert "Path outside workspace" in result.summary
    assert result.changed_files == []
    
    mock_git.restore_checkpoint.assert_called_once()


@pytest.mark.anyio
async def test_fast_path_validation_failure(orchestrator, mock_git, mock_tools):
    workspace = Path("/tmp/workspace")
    request = "Create error.txt containing exactly: failure"
    
    # Simulate tool failure
    mock_write = mock_tools.get.return_value
    mock_write.execute = AsyncMock(return_value=ToolResult(call_id="call-123", success=False, error="Disk full"))
    
    result = await orchestrator.execute_task(request, workspace)
    
    assert result.status == ExecutionStatus.ROLLED_BACK
    assert "Disk full" in result.summary
    assert result.changed_files == []
    
    mock_git.restore_checkpoint.assert_called_once()


@pytest.mark.anyio
async def test_complex_task_falls_back_to_full_pipeline(orchestrator, mock_git):
    workspace = Path("/tmp/workspace")
    request = "Refactor the authentication module"
    
    with patch("forgeai.orchestrator.TaskIntelligenceAgent") as MockTIAgent, \
         patch("forgeai.orchestrator.EnvironmentIntelligenceAgent") as MockEnvAgent, \
         patch("forgeai.orchestrator.PlanningAgent") as MockPlanner, \
         patch("forgeai.orchestrator.TestStrategyAgent") as MockTestAgent, \
         patch("forgeai.orchestrator.CodingAgent") as MockCoder, \
         patch("forgeai.orchestrator.RepositoryScanner") as MockRepoScanner, \
         patch("forgeai.orchestrator.DependencyDiscovery") as MockDepDiscovery:
        
        # Setup mocks to simulate successful pipeline
        dep_instance = MockDepDiscovery.return_value
        dep_instance.discover = MagicMock(return_value=(MagicMock(), MagicMock()))
        
        ti_instance = MockTIAgent.return_value
        ti_instance.analyze = AsyncMock(return_value=EngineeringTask(original_request=request, objective="Refactor", status=TaskIntelligenceStatus.READY))
        
        planner_instance = MockPlanner.return_value
        planner_instance.plan = AsyncMock(return_value=MagicMock())
        
        test_instance = MockTestAgent.return_value
        test_instance.generate_strategy = AsyncMock(return_value=MagicMock())
        
        coder_instance = MockCoder.return_value
        coder_instance.run = AsyncMock(return_value=CodingResult(
            task_id="tid",
            success=True,
            final_phase=CodingPhase.COMPLETED,
            session=CodingSession(session_id="s", task_id="t", plan_id="p"),
            changed_files=["auth.py"],
            summary="Refactored auth",
            committed=True,
            commit_hash="abcdef",
        ))
        
        result = await orchestrator.execute_task(request, workspace)
        
        assert result.status == ExecutionStatus.COMPLETED
        assert result.changed_files == ["auth.py"]
        
        # Verify full pipeline agents were invoked
        ti_instance.analyze.assert_called_once()
        planner_instance.plan.assert_called_once()
        test_instance.generate_strategy.assert_called_once()
        coder_instance.run.assert_called_once()


@pytest.mark.anyio
async def test_fast_path_fresh_repo(orchestrator, mock_git, mock_tools):
    workspace = Path("/tmp/workspace")
    request = "Create initial.txt containing exactly: init"
    
    # Simulate fresh repo where checkpoint_hash is None (no HEAD)
    mock_git.create_checkpoint = AsyncMock(return_value=WorkspaceCheckpoint(
        task_id="tid", commit_hash=None, branch="test-branch", 
        status=GitStatus(branch="main", is_clean=True, unstaged_changes=[], staged_changes=[], untracked_changes=[])
    ))
    
    result = await orchestrator.execute_task(request, workspace)
    
    assert result.status == ExecutionStatus.COMPLETED
    assert result.changed_files == ["initial.txt"]
    assert result.success is True
    
    mock_tools.get.assert_called_with("write_file")
