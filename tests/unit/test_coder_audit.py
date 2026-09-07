"""Audit and hardening tests for Coding Agent Phase 11."""

import json
from pathlib import Path
from typing import Any

import pytest

from forgeai.agents.coder import CodingAgent
from forgeai.agents.models import AgentTask, CodingPhase, EngineeringPlan
from forgeai.config.settings import settings
from forgeai.git.models import (
    GitStatus,
    WorkspaceCheckpoint,
    GitCommit,
    GitBranch,
    GitDiff,
)
from forgeai.llm.models import LLMRequest, LLMResponse, LLMToolCall
from forgeai.llm.providers.mock import MockLLMProvider
from forgeai.sandbox.models import CommandResult
from tests.unit.test_coder import (
    MockGitService,
    MockSandboxManager,
    agent,
    tool_registry,
)  # noqa: F401, F811
from forgeai.tools.execution.run_command import RunCommandTool


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


@pytest.mark.anyio
async def test_no_change_task(
    agent: CodingAgent, task: AgentTask, plan: EngineeringPlan, tmp_path: Path
) -> None:
    def factory(req: LLMRequest) -> LLMResponse:
        decision = {
            "action": "finish",
            "rationale_summary": "Done",
            "target_files": [],
            "completion_requested": True,
        }
        return LLMResponse(model="mock", content=json.dumps(decision))

    agent.llm_client = MockLLMProvider(response_factory=factory)
    settings.coding_run_validation = False
    result = await agent.run(task, plan, tmp_path)
    assert result.success is True
    assert result.final_phase == CodingPhase.COMPLETED


@pytest.mark.anyio
async def test_mutation_outside_affected_rejected(
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
                        arguments={"path": "src/unauthorized.py", "content": "x"},
                    )
                ],
            )
        elif call_count == 3:
            assert any(
                msg.content and "Security Violation" in msg.content
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


@pytest.mark.anyio
async def test_absolute_path_rejected(
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
                        arguments={"path": "/tmp/secret.py", "content": "x"},
                    )
                ],
            )
        elif call_count == 3:
            assert any(
                msg.content and "Security Violation" in msg.content
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


@pytest.mark.anyio
async def test_traversal_rejected(
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
                        arguments={"path": "../secret.py", "content": "x"},
                    )
                ],
            )
        elif call_count == 3:
            assert any(
                msg.content and "Security Violation" in msg.content
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


@pytest.mark.anyio
async def test_forbidden_command(
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
                        arguments={"path": "src/file_a.py", "content": "x"},
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
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-2",
                        name="run_command",
                        arguments={"command": ["bash", "-c", "rm -rf /"]},
                    )
                ],
            )
        elif call_count == 5:
            assert any(
                msg.content and "Security Violation" in msg.content
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
        raise RuntimeError(f"Too many calls: {call_count}")

    agent.llm_client = MockLLMProvider(response_factory=factory)
    result = await agent.run(task, plan, tmp_path)
    assert result.success is True


@pytest.mark.anyio
async def test_validation_failure_triggers_repair(
    agent: CodingAgent, task: AgentTask, plan: EngineeringPlan, tmp_path: Path
) -> None:
    # We need MockSandboxManager to fail once, then succeed.
    class FailingSandboxManager(MockSandboxManager):
        def __init__(self) -> None:
            self.calls = 0

        async def create_sandbox(self, config: Any, workspace_root: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                from tests.unit.test_coder import MockSandbox

                return MockSandbox(
                    CommandResult(
                        exit_code=1,
                        stdout="error",
                        stderr="",
                        duration_seconds=1.0,
                        timed_out=False,
                        success=False,
                        truncated=False,
                    )
                )
            from tests.unit.test_coder import MockSandbox

            return MockSandbox(
                CommandResult(
                    exit_code=0,
                    stdout="success",
                    stderr="",
                    duration_seconds=1.0,
                    timed_out=False,
                    success=True,
                    truncated=False,
                )
            )

    settings.coding_run_validation = True
    del agent.tool_registry._tools["run_command"]
    agent.tool_registry.register(RunCommandTool(FailingSandboxManager()))

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
                        arguments={"path": "src/file_a.py", "content": "x"},
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
                "action": "repair",
                "rationale_summary": "Repairing",
                "target_files": [],
                "completion_requested": False,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))
        elif call_count == 6:
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-3",
                        name="write_file",
                        arguments={"path": "src/file_a.py", "content": "y"},
                    )
                ],
            )
        elif call_count == 7:
            decision = {
                "action": "finish",
                "rationale_summary": "Fixed",
                "target_files": [],
                "completion_requested": True,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))
        elif call_count == 8:
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-4", name="run_command", arguments={"command": ["pytest"]}
                    )
                ],
            )
        elif call_count == 9:
            decision = {
                "action": "finish",
                "rationale_summary": "Done",
                "target_files": [],
                "completion_requested": True,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))

        raise RuntimeError(f"Too many calls: {call_count}")

    agent.llm_client = MockLLMProvider(response_factory=factory)
    result = await agent.run(task, plan, tmp_path)
    assert result.success is True
    assert result.final_phase == CodingPhase.COMPLETED


@pytest.mark.anyio
async def test_repair_exhaustion(
    agent: CodingAgent, task: AgentTask, plan: EngineeringPlan, tmp_path: Path
) -> None:
    settings.coding_max_repair_iterations = 1
    settings.coding_run_validation = True

    class FailingSandboxManager(MockSandboxManager):
        async def create_sandbox(self, config: Any, workspace_root: Any) -> Any:
            from tests.unit.test_coder import MockSandbox

            return MockSandbox(
                CommandResult(
                    exit_code=1,
                    stdout="error",
                    stderr="",
                    duration_seconds=1.0,
                    timed_out=False,
                    success=False,
                    truncated=False,
                )
            )

    del agent.tool_registry._tools["run_command"]
    agent.tool_registry.register(RunCommandTool(FailingSandboxManager()))

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
                        arguments={"path": "src/file_a.py", "content": "x"},
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
                "action": "repair",
                "rationale_summary": "Repairing",
                "target_files": [],
                "completion_requested": False,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))
        elif call_count == 6:
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-3",
                        name="write_file",
                        arguments={"path": "src/file_a.py", "content": "y"},
                    )
                ],
            )
        elif call_count == 7:
            decision = {
                "action": "finish",
                "rationale_summary": "Fixed",
                "target_files": [],
                "completion_requested": True,
            }
            return LLMResponse(model="mock", content=json.dumps(decision))
        elif call_count == 8:
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-4", name="run_command", arguments={"command": ["pytest"]}
                    )
                ],
            )
        return LLMResponse(model="mock", content="{}")

    agent.llm_client = MockLLMProvider(response_factory=factory)
    result = await agent.run(task, plan, tmp_path)
    assert result.success is False
    assert result.final_phase == CodingPhase.ROLLED_BACK


@pytest.mark.anyio
async def test_unrelated_staged_changes_blocked_at_start(
    agent: CodingAgent, task: AgentTask, plan: EngineeringPlan, tmp_path: Path
) -> None:
    mock_git = agent.git_service
    from forgeai.git.models import GitChange, ChangeType

    # Using ignore typing as MockGitService properties might have loose types in tests
    mock_git.status = GitStatus(
        branch="main",
        is_clean=False,
        untracked_changes=[],
        unstaged_changes=[],
        staged_changes=[
            GitChange(path="src/other.py", change_type=ChangeType.MODIFIED, staged=True)
        ],
    )  # type: ignore[attr-defined]

    result = await agent.run(task, plan, tmp_path)
    assert result.success is False
    assert result.final_phase == CodingPhase.ROLLED_BACK
    assert "Workspace must be completely clean before coding" in result.error_message


@pytest.mark.anyio
async def test_final_diff_authorization_failure(
    agent: CodingAgent, task: AgentTask, plan: EngineeringPlan, tmp_path: Path
) -> None:
    call_count = 0

    def factory(req: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
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
    status_calls = 0

    async def mock_get_status() -> GitStatus:
        nonlocal status_calls
        status_calls += 1
        if status_calls == 1:
            return GitStatus(
                branch="main",
                is_clean=True,
                untracked_changes=[],
                unstaged_changes=[],
                staged_changes=[],
            )
        from forgeai.git.models import GitChange, ChangeType

        return GitStatus(
            branch="main",
            is_clean=False,
            untracked_changes=[],
            unstaged_changes=[],
            staged_changes=[
                GitChange(
                    path="src/unauthorized.py", change_type=ChangeType.MODIFIED, staged=True
                )
            ],
        )

    agent.git_service.get_status = mock_get_status  # type: ignore

    result = await agent.run(task, plan, tmp_path)
    assert result.success is False
    assert result.final_phase == CodingPhase.ROLLED_BACK
    assert "Unauthorized file was modified" in result.error_message
