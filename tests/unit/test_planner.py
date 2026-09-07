"""Tests for the Planning Agent."""

import json

import pytest

from forgeai.agents.errors import PlanValidationError
from forgeai.agents.models import AgentTask
from forgeai.agents.planner import PlanningAgent
from forgeai.llm.errors import LLMTimeoutError
from forgeai.llm.models import LLMRequest, LLMResponse
from forgeai.llm.providers.mock import MockLLMProvider
from forgeai.repository.models import (
    RepositoryEntryPoint,
    RepositoryFile,
    RepositorySnapshot,
    RepositorySymbol,
)


@pytest.fixture
def mock_snapshot() -> RepositorySnapshot:
    """A realistic but minimal deterministic repository snapshot."""
    snapshot = RepositorySnapshot(
        repository_root="/mock/repo",
        total_files_found=3,
        total_analyzed_files=2,
    )

    snapshot.files.append(
        RepositoryFile(
            relative_path="src/main.py",
            extension=".py",
            language="Python",
            size_bytes=1024,
        )
    )
    snapshot.files.append(
        RepositoryFile(
            relative_path="pyproject.toml",
            extension=".toml",
            language="TOML",
            size_bytes=512,
        )
    )

    snapshot.important_files.append("pyproject.toml")
    snapshot.test_files.append("tests/test_main.py")

    snapshot.symbols.append(
        RepositorySymbol(
            name="AppConfig",
            symbol_type="class",
            file_path="src/main.py",
            line_number=10,
        )
    )
    snapshot.entry_points.append(
        RepositoryEntryPoint(
            file_path="src/main.py",
            reason="Found `if __name__ == '__main__':` block.",
            confidence=0.9,
        )
    )
    return snapshot


@pytest.fixture
def mock_task() -> AgentTask:
    return AgentTask(
        task_id="task-1",
        description=(
            "Add a new pagination feature to the users endpoint and update AppConfig."
        ),
    )


@pytest.mark.anyio
async def test_planner_success(
    mock_snapshot: RepositorySnapshot, mock_task: AgentTask
) -> None:
    def factory(req: LLMRequest) -> LLMResponse:
        # Check that context selection included the right things
        prompt = req.messages[1].content
        assert "AppConfig" in prompt
        assert "pyproject.toml" in prompt

        # Valid EngineeringPlan JSON
        plan_dict = {
            "plan_id": "plan-123",
            "task_description": mock_task.description,
            "task_interpretation": "Implement pagination for users.",
            "discovered_facts": ["src/main.py contains AppConfig"],
            "assumptions": ["Assuming SQLAlchemy is used for pagination"],
            "proposed_changes": "Add skip/limit to endpoint.",
            "affected_files": ["src/main.py"],
            "excluded_files": ["pyproject.toml"],
            "steps": [
                {
                    "step_number": 1,
                    "objective": "Add limit/skip parameters",
                    "target_files": ["src/main.py"],
                    "change_description": "Modify users endpoint signature.",
                    "dependencies_on_steps": [],
                    "validation_requirement": "Unit tests pass.",
                }
            ],
            "dependencies_to_add": [],
            "tests_to_add_or_update": ["tests/test_main.py"],
            "validation_strategy": "Run tests.",
            "risks": ["Breaking API change."],
            "confidence": 0.95,
        }
        return LLMResponse(content=json.dumps(plan_dict), model=req.model)

    provider = MockLLMProvider(response_factory=factory)
    planner = PlanningAgent(llm_client=provider)

    plan = await planner.plan(mock_task, mock_snapshot)

    assert plan.plan_id == "plan-123"
    assert len(plan.steps) == 1
    assert plan.steps[0].step_number == 1
    assert plan.confidence == 0.95


@pytest.mark.anyio
async def test_planner_malformed_json(
    mock_snapshot: RepositorySnapshot, mock_task: AgentTask
) -> None:
    provider = MockLLMProvider(default_response="Not JSON at all")
    planner = PlanningAgent(llm_client=provider)

    with pytest.raises(PlanValidationError) as exc_info:
        await planner.plan(mock_task, mock_snapshot)

    assert "Failed to parse EngineeringPlan" in str(exc_info.value)


@pytest.mark.anyio
async def test_planner_missing_fields(
    mock_snapshot: RepositorySnapshot, mock_task: AgentTask
) -> None:
    # Valid JSON but missing required fields
    provider = MockLLMProvider(default_response='{"plan_id": "123"}')
    planner = PlanningAgent(llm_client=provider)

    with pytest.raises(PlanValidationError) as exc_info:
        await planner.plan(mock_task, mock_snapshot)

    assert "Failed to parse EngineeringPlan" in str(exc_info.value)


@pytest.mark.anyio
async def test_planner_provider_failure(
    mock_snapshot: RepositorySnapshot, mock_task: AgentTask
) -> None:
    provider = MockLLMProvider(simulate_error=LLMTimeoutError("API timed out"))
    planner = PlanningAgent(llm_client=provider)

    with pytest.raises(LLMTimeoutError):
        await planner.plan(mock_task, mock_snapshot)
