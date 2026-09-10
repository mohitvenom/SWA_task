"""Integration tests for the Application Orchestrator."""

import json
from pathlib import Path
from typing import Any

import anyio
import pytest

from forgeai.agents.coder import CodingAgent
from forgeai.agents.models import (
    CodingPhase,
    ExecutionStatus,
    TaskIntelligenceStatus,
)
from forgeai.config.settings import settings
from forgeai.git.interface import GitService
from forgeai.git.service import GitCLIWorkspaceService
from forgeai.llm.client import LLMClient
from forgeai.llm.models import LLMRequest, LLMResponse, LLMToolCall
from forgeai.orchestrator import ApplicationOrchestrator
from forgeai.tools.errors import SecurityViolationError
from forgeai.tools.registry import ToolRegistry


class OrchestratorMockLLM(LLMClient):
    """A mock LLM that produces predictable responses for E2E orchestration tests."""
    
    def __init__(self, scenario: str = "A"):
        self.scenario = scenario
        self.call_count = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        content = request.messages[0].content
        self.call_count += 1
        
        # Scenario B: Blocking Ambiguity
        if self.scenario == "B" and "Task Intelligence" in content:
            return LLMResponse(
                model="mock",
                content=json.dumps({
                    "task_id": "test",
                    "original_request": "Do something vague",
                    "objective": "Unknown",
                    "requirements": [],
                    "acceptance_criteria": [],
                    "constraints": [],
                    "assumptions": [],
                    "ambiguities": [{"question": "What?", "severity": "BLOCKING"}],
                    "risk_level": "HIGH",
                    "status": "NEEDS_CLARIFICATION"
                })
            )
            
        # Standard responses for other phases
        if "Task Intelligence" in content:
            return LLMResponse(
                model="mock",
                content=json.dumps({
                    "task_id": "test",
                    "original_request": "Do something",
                    "objective": "Fix it",
                    "requirements": [],
                    "acceptance_criteria": [],
                    "constraints": [],
                    "assumptions": [],
                    "ambiguities": [],
                    "risk_level": "LOW",
                    "status": "READY"
                })
            )
        elif "Planning Agent" in content:
            return LLMResponse(
                model="mock",
                content=json.dumps({
                    "plan_id": "p1",
                    "task_description": "Fix",
                    "task_interpretation": "Fix",
                    "proposed_changes": "Fix",
                    "validation_strategy": "none",
                    "affected_files": ["src/foo.py"],
                    "excluded_files": [],
                    "confidence": 1.0,
                    "change_set": {
                        "objective": "Fix",
                        "initial_files": [{"file_path": "src/foo.py", "operation": "MODIFY", "rationale": ""}],
                        "authorized_files": ["src/foo.py"],
                        "status": "AUTHORIZED"
                    }
                })
            )
        elif "Test Strategy" in content:
            return LLMResponse(
                model="mock",
                content=json.dumps({
                    "validation_goals": [],
                    "test_cases": [],
                    "relevant_existing_tests": [],
                    "proposed_tests": [],
                    "validation_commands": [],
                    "status": "READY"
                })
            )
        elif "Failure Diagnosis" in content:
            return LLMResponse(
                model="mock",
                content=json.dumps({
                    "failure_id": "f1",
                    "category": "TEST_FAILURE",
                    "severity": "HIGH",
                    "symptom_summary": "Failed",
                    "root_cause_analysis": "Bug",
                    "confidence": 1.0,
                    "status": "DIAGNOSED",
                    "repair_plan": {
                        "objective": "Fix",
                        "root_cause_addressed": "Bug",
                        "proposed_actions": [],
                        "affected_files": ["src/foo.py"],
                        "risk": "LOW"
                    }
                })
            )
        elif "review the code changes" in content:
            if self.scenario == "E":
                return LLMResponse(
                    model="mock",
                    content=json.dumps({
                        "status": "REJECTED",
                        "rationale_summary": "Bad",
                        "findings": []
                    })
                )
            return LLMResponse(
                model="mock",
                content=json.dumps({
                    "status": "APPROVED",
                    "rationale_summary": "Good",
                    "findings": []
                })
            )
            
        # Coding Agent
        if self.scenario == "A":
            return LLMResponse(model="mock", content=json.dumps({"action": "finish", "completion_requested": True, "rationale_summary": "Done"}))
        elif self.scenario == "F":
            # Security Violation
            raise SecurityViolationError("Simulated security violation")
        elif self.scenario == "G":
            # Infrastructure Failure
            raise RuntimeError("Simulated infrastructure failure")
            
        return LLMResponse(model="mock", content=json.dumps({"action": "finish", "completion_requested": True, "rationale_summary": "Done"}))


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    import subprocess
    d = tmp_path / "repo"
    d.mkdir()
    subprocess.run(["git", "init"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, check=True)
    (d / "src").mkdir()
    (d / "src" / "foo.py").write_text("print('foo')\n")
    subprocess.run(["git", "add", "."], cwd=d, check=True)
    subprocess.run(["git", "commit", "-m", "Init"], cwd=d, check=True)
    return d


@pytest.fixture
def orchestrator(repo_dir: Path) -> ApplicationOrchestrator:
    settings.autonomous_execution_enabled = True
    settings.memory_enabled = False
    llm = OrchestratorMockLLM()
    registry = ToolRegistry()
    git_service = GitCLIWorkspaceService(repo_dir)
    return ApplicationOrchestrator(llm, registry, git_service)


@pytest.mark.anyio
async def test_scenario_A_successful_task(orchestrator: ApplicationOrchestrator, repo_dir: Path) -> None:
    """Scenario A: Successful Task."""
    orchestrator.llm.scenario = "A" # type: ignore
    result = await orchestrator.execute_task("Do something", repo_dir)
    print("SCENARIO A RESULT:", result.summary, result.failure_information)
    assert result.status == ExecutionStatus.COMPLETED
    assert result.success is True


@pytest.mark.anyio
async def test_scenario_B_blocking_ambiguity(orchestrator: ApplicationOrchestrator, repo_dir: Path) -> None:
    """Scenario B: Blocking Ambiguity."""
    orchestrator.llm.scenario = "B" # type: ignore
    result = await orchestrator.execute_task("Do vague thing", repo_dir)
    assert result.status == ExecutionStatus.NEEDS_CLARIFICATION
    assert result.success is False


@pytest.mark.anyio
async def test_scenario_F_security_violation(orchestrator: ApplicationOrchestrator, repo_dir: Path) -> None:
    """Scenario F: Security Violation."""
    orchestrator.llm.scenario = "F" # type: ignore
    result = await orchestrator.execute_task("Hack it", repo_dir)
    assert result.status == ExecutionStatus.SECURITY_REJECTED
    
    # Verify rollback via git clean state
    status = await orchestrator.git.get_status()
    assert status.is_clean is True


@pytest.mark.anyio
async def test_scenario_G_infrastructure_failure(orchestrator: ApplicationOrchestrator, repo_dir: Path) -> None:
    """Scenario G: Infrastructure Failure."""
    orchestrator.llm.scenario = "G" # type: ignore
    result = await orchestrator.execute_task("Break it", repo_dir)
    assert result.status == ExecutionStatus.ROLLED_BACK
    
    status = await orchestrator.git.get_status()
    assert status.is_clean is True


@pytest.mark.anyio
async def test_scenario_I_cancellation_during_coding(orchestrator: ApplicationOrchestrator, repo_dir: Path) -> None:
    """Scenario I: Cancellation during coding rolls back."""
    cancel_scope = anyio.CancelScope()
    # We simulate a cancellation using AnyIO semantics
    class CancelledLLM(OrchestratorMockLLM):
        async def generate(self, request: LLMRequest) -> LLMResponse:
            if "Engineering Plan:" in request.messages[0].content:
                cancel_scope.cancel()
                await anyio.sleep(0.1) # yield to raise
            return await super().generate(request)
            
    orchestrator.llm = CancelledLLM("A")
    
    with cancel_scope:
        await orchestrator.execute_task("Do something", repo_dir)
        
    assert cancel_scope.cancel_called is True
    status = await orchestrator.git.get_status()
    assert status.is_clean is True


@pytest.mark.anyio
async def test_autonomous_disabled(orchestrator: ApplicationOrchestrator, repo_dir: Path) -> None:
    """Verify autonomous mode disabled behavior."""
    settings.autonomous_execution_enabled = False
    result = await orchestrator.execute_task("Do something", repo_dir)
    assert result.status == ExecutionStatus.SECURITY_REJECTED
    assert "Autonomous execution disabled" in result.summary
