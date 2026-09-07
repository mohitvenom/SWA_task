"""Unit tests for the Coding Agent."""

import json
from pathlib import Path
from typing import Any

import pytest

from forgeai.agents.coder import CodingAgent, CodingPolicy
from forgeai.agents.errors import AgentMaxIterationsError
from forgeai.agents.models import (
    AgentTask,
    CodingDecision,
    CodingPhase,
    EngineeringPlan,
    PlanStep,
)
from forgeai.config.settings import settings
from forgeai.git.interface import GitService
from forgeai.git.models import (
    GitStatus,
    WorkspaceCheckpoint,
    GitChange,
    GitBranch,
    GitCommit,
    GitDiff,
)
from forgeai.llm.models import LLMRequest, LLMResponse, LLMToolCall
from forgeai.llm.errors import LLMError
from forgeai.llm.providers.mock import MockLLMProvider
from forgeai.sandbox.interface import Sandbox, SandboxManager
from forgeai.sandbox.models import CommandRequest, CommandResult, SandboxConfig
from forgeai.tools.errors import SecurityViolationError
from forgeai.tools.registry import ToolRegistry
from forgeai.tools.repository.write_file import WriteFileTool
from forgeai.tools.repository.read_file import ReadFileTool
from forgeai.tools.repository.list_files import ListFilesTool
from forgeai.tools.execution.run_command import RunCommandTool


class MockSandbox(Sandbox):
    def __init__(self, result: CommandResult):
        self.result = result

    async def execute(self, request: CommandRequest) -> CommandResult:
        return self.result

    async def destroy(self) -> None:
        pass


class MockSandboxManager(SandboxManager):
    def __init__(self, result: CommandResult | None = None):
        self.result = result or CommandResult(
            exit_code=0,
            stdout="success",
            stderr="",
            duration_seconds=1.0,
            timed_out=False,
            success=True,
        )

    async def create_sandbox(
        self, config: SandboxConfig, workspace_root: Path
    ) -> Sandbox:
        return MockSandbox(self.result)


class MockGitService(GitService):
    def __init__(self) -> None:
        self.status = GitStatus(
            branch="main",
            is_clean=True,
            untracked_changes=[],
            unstaged_changes=[],
            staged_changes=[],
        )
        self.commit_history: list[tuple[str, list[str], str]] = []
        self.rollbacks: list[WorkspaceCheckpoint] = []

    async def inspect_repository(self) -> GitStatus:
        return self.status

    async def get_status(self) -> GitStatus:
        return self.status

    async def create_branch(self, task_id: str) -> GitBranch:
        return GitBranch(
            name=f"forgeai/task/{task_id}", is_current=True, is_remote=False
        )

    async def checkout_branch(self, name: str) -> None:
        pass

    async def get_diff(self) -> GitDiff:
        return GitDiff(
            changed_files=0, insertions=0, deletions=0, patch="", truncated=False
        )

    async def stage_files(self, paths: list[str]) -> None:
        pass

    async def commit(self, message: str, paths: list[str]) -> GitCommit:
        commit_hash = "abc456"
        self.commit_history.append((message, paths, commit_hash))
        return GitCommit(commit_hash=commit_hash, message=message, branch="main")

    async def create_checkpoint(self, task_id: str) -> WorkspaceCheckpoint:
        return WorkspaceCheckpoint(
            task_id=task_id,
            commit_hash="initial_hash",
            branch="main",
            status=self.status,
        )

    async def rollback_files(self, paths: list[str]) -> None:
        pass

    async def restore_checkpoint(self, checkpoint: WorkspaceCheckpoint) -> None:
        self.rollbacks.append(checkpoint)


@pytest.fixture
def plan() -> EngineeringPlan:
    return EngineeringPlan(
        plan_id="plan-1",
        task_description="Implement feature X",
        task_interpretation="Do X",
        proposed_changes="Add file_a.py",
        affected_files=["src/file_a.py"],
        excluded_files=["src/secret.py"],
        validation_strategy="pytest",
        confidence=1.0,
    )


@pytest.fixture
def task() -> AgentTask:
    return AgentTask(task_id="task-1", description="Implement feature X")


@pytest.fixture
def tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(ReadFileTool())
    registry.register(ListFilesTool())
    registry.register(RunCommandTool(MockSandboxManager()))
    return registry


@pytest.fixture
def agent(tool_registry: ToolRegistry) -> CodingAgent:
    llm = MockLLMProvider()
    git = MockGitService()
    return CodingAgent(llm_client=llm, tool_registry=tool_registry, git_service=git)


@pytest.mark.anyio
async def test_A_successful_coding_task(
    agent: CodingAgent, task: AgentTask, plan: EngineeringPlan, tmp_path: Path
) -> None:
    call_count = 0

    def factory(req: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            decision = {
                "action": "modify",
                "rationale_summary": "Start implementing",
                "target_files": [],
                "completion_requested": False,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))
        elif call_count == 2:
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-1",
                        name="write_file",
                        arguments={
                            "path": "src/file_a.py",
                            "content": "print('x')",
                            "overwrite": False,
                        },
                    )
                ],
            )
        elif call_count == 3:
            decision = {
                "action": "finish",
                "rationale_summary": "Done",
                "target_files": [],
                "completion_requested": True,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))
        elif call_count == 4:
            # VALIDATING phase starts
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-2", name="run_command", arguments={"command": ["pytest"]}
                    )
                ],
            )
        elif call_count == 5:
            decision = {
                "action": "finish",
                "rationale_summary": "Validation passed",
                "target_files": [],
                "completion_requested": True,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))
        raise RuntimeError("Too many calls")

    agent.llm_client = MockLLMProvider(response_factory=factory)
    settings.coding_run_validation = True

    # We must mock git status to return something as changed so we don't fail changed_files=0 check? No, changed files can be 0.
    # Wait, if we wrote a file, the real git would see it. But we are using MockGitService which says is_clean=True always.

    result = await agent.run(task, plan, tmp_path)

    assert result.success is True
    assert result.final_phase == CodingPhase.COMPLETED
    assert call_count == 5

    # Ensure file was actually written
    assert (tmp_path / "src" / "file_a.py").exists()


@pytest.mark.anyio
async def test_E_mutation_excluded_file_rejected(
    agent: CodingAgent, task: AgentTask, plan: EngineeringPlan, tmp_path: Path
) -> None:
    call_count = 0

    def factory(req: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            decision = {
                "action": "modify",
                "rationale_summary": "Start",
                "target_files": [],
                "completion_requested": False,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))
        elif call_count == 2:
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-1",
                        name="write_file",
                        arguments={
                            "path": "src/secret.py",
                            "content": "hack",
                            "overwrite": False,
                        },
                    )
                ],
            )
        elif call_count == 3:
            assert any(
                msg.content
                and "Security Violation: Path 'src/secret.py' is explicitly excluded"
                in msg.content
                for msg in req.messages
                if msg.role == "tool"
            )
            decision = {
                "action": "finish",
                "rationale_summary": "Done",
                "target_files": [],
                "completion_requested": True,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))
        elif call_count == 4:
            decision = {
                "action": "finish",
                "rationale_summary": "Done",
                "target_files": [],
                "completion_requested": True,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))

        raise RuntimeError("Too many calls")

    agent.llm_client = MockLLMProvider(response_factory=factory)
    settings.coding_run_validation = False
    result = await agent.run(task, plan, tmp_path)
    assert result.success is True
    assert not (tmp_path / "src" / "secret.py").exists()


@pytest.mark.anyio
async def test_W_rollback_after_failure(
    agent: CodingAgent, task: AgentTask, plan: EngineeringPlan, tmp_path: Path
) -> None:
    def factory(req: LLMRequest) -> LLMResponse:
        raise LLMError("Simulated LLM crash")

    agent.llm_client = MockLLMProvider(response_factory=factory)

    mock_git = agent.git_service
    assert isinstance(mock_git, MockGitService)

    result = await agent.run(task, plan, tmp_path)

    assert result.success is False
    assert result.final_phase == CodingPhase.ROLLED_BACK
    assert len(mock_git.rollbacks) == 1
    assert mock_git.rollbacks[0].commit_hash == "initial_hash"


@pytest.mark.anyio
async def test_C_read_only_inspection_before_modification(
    agent: CodingAgent, task: AgentTask, plan: EngineeringPlan, tmp_path: Path
) -> None:
    # Test that read tools are allowed in INSPECTING, but write tools are blocked.
    call_count = 0

    def factory(req: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Still in INSPECTING phase, try a mutation
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-1",
                        name="write_file",
                        arguments={
                            "path": "src/file_a.py",
                            "content": "x",
                            "overwrite": False,
                        },
                    )
                ],
            )
        elif call_count == 2:
            assert any(
                msg.content and "not allowed in INSPECTING phase" in msg.content
                for msg in req.messages
                if msg.role == "tool"
            )
            decision = {
                "action": "finish",
                "rationale_summary": "Done",
                "target_files": [],
                "completion_requested": True,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))

        raise RuntimeError("Too many calls")

    agent.llm_client = MockLLMProvider(response_factory=factory)
    settings.coding_run_validation = False
    result = await agent.run(task, plan, tmp_path)
    assert result.success is True
