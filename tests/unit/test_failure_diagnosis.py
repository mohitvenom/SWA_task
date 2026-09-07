import json
from unittest.mock import MagicMock

import pytest

from forgeai.agents.errors import (
    FailureDiagnosisParseError,
    RepairPlanValidationError,
)
from forgeai.agents.failure_diagnosis import FailureDiagnosisAgent
from forgeai.agents.models import (
    DiagnosisStatus,
    EngineeringPlan,
    EngineeringTask,
    FailureCategory,
    FailureDiagnosis,
    FailureSeverity,
    RepairAction,
    RepairPlan,
    TaskRiskLevel,
    TestStrategy,
    TestStrategyStatus,
)


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    # Ensure it's async
    async def mock_generate(*args, **kwargs):
        return llm.generate.return_value
    llm.generate = MagicMock(side_effect=mock_generate)
    return llm


@pytest.fixture
def agent(mock_llm: MagicMock) -> FailureDiagnosisAgent:
    return FailureDiagnosisAgent(llm_client=mock_llm)


@pytest.fixture
def task() -> EngineeringTask:
    return EngineeringTask(
        task_id="task-123",
        original_request="Fix the bug",
        objective="Fix the bug",
        requirements=["Ensure x is positive"],
        acceptance_criteria=["Function returns > 0"],
        risk_level=TaskRiskLevel.LOW,
    )


@pytest.fixture
def plan() -> EngineeringPlan:
    return EngineeringPlan(
        plan_id="plan-1",
        task_id="task-123",
        task_description="Fix it",
        task_interpretation="Fix it",
        proposed_changes="Modify main.py",
        affected_files=["src/main.py"],
        excluded_files=["src/secret.py"],
        validation_strategy="Run tests",
        confidence=1.0,
    )


@pytest.fixture
def strategy() -> TestStrategy:
    return TestStrategy(
        task_id="task-123",
        validation_goals=["Check x is positive"],
        validation_commands=["pytest test_main.py"],
        status=TestStrategyStatus.READY,
    )


@pytest.mark.anyio
async def test_successful_diagnosis_and_repair(
    agent: FailureDiagnosisAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
    strategy: TestStrategy,
) -> None:
    class MockResponse:
        content = json.dumps(
            {
                "failure_id": "f-123",
                "category": "TEST_FAILURE",
                "severity": "HIGH",
                "symptom_summary": "Test failed with AssertionError",
                "root_cause_analysis": "The function returns 0 instead of 1.",
                "confidence": 0.9,
                "status": "DIAGNOSED",
                "repair_plan": {
                    "objective": "Fix return value",
                    "root_cause_addressed": "Returning 0",
                    "affected_files": ["src/main.py"],
                    "risk": "LOW",
                    "proposed_actions": [
                        {
                            "target_file": "src/main.py",
                            "rationale": "Must return > 0",
                            "expected_effect": "Test passes",
                        }
                    ],
                },
            }
        )
    mock_llm.generate.return_value = MockResponse()

    diagnosis = await agent.diagnose(
        task=task,
        plan=plan,
        strategy=strategy,
        validation_results=[{"success": False, "output": "AssertionError"}],
        changed_files=["src/main.py"],
    )

    assert diagnosis.category == FailureCategory.TEST_FAILURE
    assert diagnosis.repair_plan is not None
    assert len(diagnosis.repair_plan.proposed_actions) == 1
    assert diagnosis.repair_plan.proposed_actions[0].target_file == "src/main.py"


@pytest.mark.anyio
async def test_infrastructure_failure_heuristic(
    agent: FailureDiagnosisAgent,
    task: EngineeringTask,
    plan: EngineeringPlan,
) -> None:
    diagnosis = await agent.diagnose(
        task=task,
        plan=plan,
        strategy=None,
        validation_results=[{"success": False, "output": "Docker unavailable. Is the daemon running?"}],
        changed_files=[],
    )

    assert diagnosis.category == FailureCategory.ENVIRONMENT_ERROR
    assert diagnosis.status == DiagnosisStatus.INFRASTRUCTURE_FAILURE
    assert diagnosis.repair_plan is None


@pytest.mark.anyio
async def test_llm_classified_infrastructure_failure(
    agent: FailureDiagnosisAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
) -> None:
    class MockResponse:
        content = json.dumps(
            {
                "failure_id": "f-123",
                "category": "ENVIRONMENT_ERROR",
                "severity": "CRITICAL",
                "symptom_summary": "Timeout",
                "root_cause_analysis": "Harness timed out",
                "confidence": 0.9,
                "status": "DIAGNOSED",
                "repair_plan": {
                    "objective": "None",
                    "root_cause_addressed": "None",
                    "risk": "LOW",
                    "proposed_actions": [
                        {
                            "target_file": "src/main.py",
                            "rationale": "Wait more",
                            "expected_effect": "Pass",
                        }
                    ],
                },
            }
        )
    mock_llm.generate.return_value = MockResponse()

    diagnosis = await agent.diagnose(
        task=task,
        plan=plan,
        strategy=None,
        validation_results=[{"success": False, "output": "Random timeout"}],
        changed_files=[],
    )

    # The agent strips repair plans from infra failures
    assert diagnosis.status == DiagnosisStatus.INFRASTRUCTURE_FAILURE
    assert diagnosis.repair_plan is None


@pytest.mark.anyio
async def test_repair_plan_validation_unauthorized_target(
    agent: FailureDiagnosisAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
) -> None:
    class MockResponse:
        content = json.dumps(
            {
                "failure_id": "f-123",
                "category": "TEST_FAILURE",
                "severity": "HIGH",
                "symptom_summary": "Test failed",
                "root_cause_analysis": "Bug",
                "confidence": 0.9,
                "status": "DIAGNOSED",
                "repair_plan": {
                    "objective": "Fix it",
                    "root_cause_addressed": "Bug",
                    "risk": "LOW",
                    "proposed_actions": [
                        {
                            "target_file": "src/unauthorized.py",  # Not in affected_files
                            "rationale": "Need to touch this",
                            "expected_effect": "Pass",
                        }
                    ],
                },
            }
        )
    mock_llm.generate.return_value = MockResponse()

    with pytest.raises(RepairPlanValidationError, match="not within authorized affected_files"):
        await agent.diagnose(
            task=task,
            plan=plan,
            strategy=None,
            validation_results=[],
            changed_files=[],
        )


@pytest.mark.anyio
async def test_repair_plan_validation_excluded_target(
    agent: FailureDiagnosisAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
) -> None:
    plan.affected_files.append("src/secret.py")
    class MockResponse:
        content = json.dumps(
            {
                "failure_id": "f-123",
                "category": "TEST_FAILURE",
                "severity": "HIGH",
                "symptom_summary": "Test failed",
                "root_cause_analysis": "Bug",
                "confidence": 0.9,
                "status": "DIAGNOSED",
                "repair_plan": {
                    "objective": "Fix it",
                    "root_cause_addressed": "Bug",
                    "risk": "LOW",
                    "proposed_actions": [
                        {
                            "target_file": "src/secret.py",  # Excluded!
                            "rationale": "Need to touch this",
                            "expected_effect": "Pass",
                        }
                    ],
                },
            }
        )
    mock_llm.generate.return_value = MockResponse()

    with pytest.raises(RepairPlanValidationError, match="explicitly excluded"):
        await agent.diagnose(
            task=task,
            plan=plan,
            strategy=None,
            validation_results=[],
            changed_files=[],
        )


@pytest.mark.anyio
async def test_repair_plan_validation_shell_injection(
    agent: FailureDiagnosisAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
) -> None:
    class MockResponse:
        content = json.dumps(
            {
                "failure_id": "f-123",
                "category": "TEST_FAILURE",
                "severity": "HIGH",
                "symptom_summary": "Test failed",
                "root_cause_analysis": "Bug",
                "confidence": 0.9,
                "status": "DIAGNOSED",
                "repair_plan": {
                    "objective": "Fix it",
                    "root_cause_addressed": "Bug",
                    "risk": "LOW",
                    "proposed_actions": [
                        {
                            "target_file": "src/main.py",
                            "rationale": "I will run bash -c 'rm -rf /'",
                            "expected_effect": "Pass",
                        }
                    ],
                },
            }
        )
    mock_llm.generate.return_value = MockResponse()

    with pytest.raises(RepairPlanValidationError, match="Arbitrary shell execution detected"):
        await agent.diagnose(
            task=task,
            plan=plan,
            strategy=None,
            validation_results=[],
            changed_files=[],
        )


@pytest.mark.anyio
async def test_malformed_json(
    agent: FailureDiagnosisAgent,
    mock_llm: MagicMock,
    task: EngineeringTask,
    plan: EngineeringPlan,
) -> None:
    class MockResponse:
        content = "This is not JSON"
    mock_llm.generate.return_value = MockResponse()

    with pytest.raises(FailureDiagnosisParseError):
        await agent.diagnose(
            task=task,
            plan=plan,
            strategy=None,
            validation_results=[],
            changed_files=[],
        )
