"""Unit tests for TestStrategyAgent."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from forgeai.agents.errors import TestStrategyParseError, TestStrategyValidationError
from forgeai.agents.models import (
    EngineeringPlan,
    EngineeringTask,
    TaskIntelligenceStatus,
    TaskRiskLevel,
    TestPriority,
    TestStrategyStatus,
    TestType,
)
from forgeai.agents.test_strategy import TestStrategyAgent
from forgeai.llm.errors import LLMError
from forgeai.llm.models import LLMResponse
from forgeai.repository.models import RepositorySnapshot


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.generate = AsyncMock()
    return llm


@pytest.fixture
def agent(mock_llm: MagicMock) -> TestStrategyAgent:
    return TestStrategyAgent(llm_client=mock_llm)


@pytest.fixture
def task() -> EngineeringTask:
    return EngineeringTask(
        task_id="task-1",
        original_request="Fix the bug.",
        objective="Fix bug in auth.",
        requirements=["User should log in"],
        acceptance_criteria=["Login works"],
        risk_level=TaskRiskLevel.MEDIUM,
        status=TaskIntelligenceStatus.READY,
    )


@pytest.fixture
def plan() -> EngineeringPlan:
    return EngineeringPlan(
        plan_id="plan-1",
        task_description="Fix bug",
        task_interpretation="Fix it",
        proposed_changes="Change auth.py",
        affected_files=["src/auth.py"],
        validation_strategy="Test auth",
        confidence=1.0,
    )


@pytest.fixture
def snapshot() -> RepositorySnapshot:
    return RepositorySnapshot(
        repository_root="/repo",
        files=[],
        symbols=[],
        test_files=["tests/unit/test_auth.py"],
        important_files=["README.md"],
        entry_points=[],
    )


@pytest.mark.anyio
async def test_generate_strategy_success(
    agent: TestStrategyAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
    snapshot: RepositorySnapshot,
) -> None:
    mock_llm.generate.return_value = LLMResponse(
        content=json.dumps(
            {
                "validation_goals": ["Ensure login works"],
                "relevant_existing_tests": ["tests/unit/test_auth.py"],
                "proposed_tests": ["test_login_success"],
                "test_cases": [
                    {
                        "name": "test_login_success",
                        "objective": "Verify successful login",
                        "scenario": "Valid credentials",
                        "expected_behavior": "Returns 200 OK",
                        "priority": "HIGH",
                        "test_type": "UNIT",
                    }
                ],
                "validation_commands": ["pytest tests/unit/test_auth.py"],
                "status": "READY",
            }
        ),
        model="test",
    )

    strategy = await agent.generate_strategy(task, plan, snapshot)

    assert strategy.task_id == "task-1"
    assert strategy.status == TestStrategyStatus.READY
    assert "Ensure login works" in strategy.validation_goals
    assert strategy.test_cases[0].priority == TestPriority.HIGH
    assert strategy.test_cases[0].test_type == TestType.UNIT


@pytest.mark.anyio
async def test_missing_validation_goals_with_criteria(
    agent: TestStrategyAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
    snapshot: RepositorySnapshot,
) -> None:
    # LLM returns no validation_goals but task has acceptance criteria
    mock_llm.generate.return_value = LLMResponse(
        content=json.dumps(
            {
                "validation_goals": [],
                "relevant_existing_tests": [],
                "proposed_tests": [],
                "test_cases": [],
                "validation_commands": [],
                "status": "READY",
            }
        ),
        model="test",
    )

    with pytest.raises(
        TestStrategyValidationError, match="contains no validation_goals"
    ):
        await agent.generate_strategy(task, plan, snapshot)


@pytest.mark.anyio
async def test_fabricated_existing_tests(
    agent: TestStrategyAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
    snapshot: RepositorySnapshot,
) -> None:
    mock_llm.generate.return_value = LLMResponse(
        content=json.dumps(
            {
                "validation_goals": ["Goal"],
                "relevant_existing_tests": ["tests/unit/test_made_up.py"],
                "proposed_tests": [],
                "test_cases": [
                    {
                        "name": "test_1",
                        "objective": "obj",
                        "scenario": "scen",
                        "expected_behavior": "exp",
                        "priority": "LOW",
                        "test_type": "UNIT",
                    }
                ],
                "validation_commands": ["pytest"],
                "status": "READY",
            }
        ),
        model="test",
    )

    with pytest.raises(TestStrategyValidationError, match="Fabricated repository fact"):
        await agent.generate_strategy(task, plan, snapshot)


@pytest.mark.anyio
async def test_invalid_validation_command(
    agent: TestStrategyAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
    snapshot: RepositorySnapshot,
) -> None:
    mock_llm.generate.return_value = LLMResponse(
        content=json.dumps(
            {
                "validation_goals": ["Goal"],
                "relevant_existing_tests": [],
                "proposed_tests": [],
                "test_cases": [
                    {
                        "name": "test_1",
                        "objective": "obj",
                        "scenario": "scen",
                        "expected_behavior": "exp",
                        "priority": "LOW",
                        "test_type": "UNIT",
                    }
                ],
                "validation_commands": ["rm -rf /"],
                "status": "READY",
            }
        ),
        model="test",
    )

    with pytest.raises(
        TestStrategyValidationError,
        match="does not start with a permitted safe executable",
    ):
        await agent.generate_strategy(task, plan, snapshot)


@pytest.mark.anyio
async def test_malformed_json_response(
    agent: TestStrategyAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
    snapshot: RepositorySnapshot,
) -> None:
    mock_llm.generate.return_value = LLMResponse(
        content="This is not JSON.",
        model="test",
    )

    with pytest.raises(TestStrategyParseError):
        await agent.generate_strategy(task, plan, snapshot)


@pytest.mark.anyio
async def test_llm_failure(
    agent: TestStrategyAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
    snapshot: RepositorySnapshot,
) -> None:
    mock_llm.generate.side_effect = LLMError("API Error")

    with pytest.raises(LLMError):
        await agent.generate_strategy(task, plan, snapshot)
