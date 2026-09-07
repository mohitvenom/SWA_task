"""Integration tests for the Coding Agent Review loop."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from forgeai.agents.coder import CodingAgent
from forgeai.agents.models import AgentTask, EngineeringPlan, ReviewStatus, CodingPhase
from forgeai.agents.reviewer import ReviewAgent
from forgeai.config.settings import settings
from forgeai.git.service import GitCLIWorkspaceService
from forgeai.tools.registry import ToolRegistry
from forgeai.llm.models import LLMResponse

from tests.unit.test_coder import MockLLMProvider, MockSandboxManager


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    subprocess.run(["git", "init"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=d, check=True)

    # Create initial commit so we have a HEAD
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=d, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=d, check=True)
    return d


@pytest.fixture
def plan() -> EngineeringPlan:
    return EngineeringPlan(
        plan_id="plan-1",
        task_description="Add exclamation",
        task_interpretation="Add exclamation",
        proposed_changes="Modify main.py to say hello!",
        validation_strategy="none",
        affected_files=["src/main.py"],
        excluded_files=[],
        confidence=1.0,
    )


@pytest.fixture
def task() -> AgentTask:
    return AgentTask(task_id="task-1", description="Add exclamation")


@pytest.mark.anyio
async def test_coding_review_integration_approval(repo_dir: Path, plan: EngineeringPlan, task: AgentTask):
    """Test full loop: Coding -> Validation -> Review (Approved) -> Commit."""
    settings.review_enabled = True
    settings.coding_auto_commit = True
    settings.coding_run_validation = False
    
    git_service = GitCLIWorkspaceService(repo_dir)
    registry = ToolRegistry()
    
    # Mock LLM for coder and reviewer
    class OrchestratedLLM(MockLLMProvider):
        def __init__(self):
            super().__init__()
            self.call_count = 0
            
        async def generate(self, request: Any) -> LLMResponse:
            self.call_count += 1
            if "Review Request" in request.messages[-1].content:
                # Reviewer call
                decision = {
                    "status": "APPROVED",
                    "rationale_summary": "Looks good",
                    "findings": []
                }
                return LLMResponse(model="mock", content=json.dumps(decision))
            else:
                # Coder call
                if self.call_count == 1:
                    return LLMResponse(
                        model="mock", 
                        content=json.dumps({"action": "modify", "rationale_summary": "Implementing", "completion_requested": False})
                    )
                else:
                    # Write the file directly to simulate tool effect (we aren't using the real tool)
                    (repo_dir / "src" / "main.py").write_text("print('hello!')\n")
                    return LLMResponse(
                        model="mock",
                        content=json.dumps({"action": "finish", "rationale_summary": "Done", "completion_requested": True})
                    )

    llm = OrchestratedLLM()
    review_agent = ReviewAgent(llm_client=llm, tool_registry=registry)
    agent = CodingAgent(
        llm_client=llm, 
        tool_registry=registry, 
        git_service=git_service,
        review_agent=review_agent
    )
    # Give the agent a mock sandbox manager just in case
    agent.sandbox_manager = MockSandboxManager()
    
    result = await agent.run(task, plan, repo_dir)
    
    assert result.success is True
    assert result.final_phase == CodingPhase.COMPLETED
    assert result.review_result is not None
    assert result.review_result.status == ReviewStatus.APPROVED
    assert result.committed is True
    
    # Verify git status
    status = await git_service.get_status()
    assert status.is_clean is True


@pytest.mark.anyio
async def test_coding_review_integration_rejection_rollback(repo_dir: Path, plan: EngineeringPlan, task: AgentTask):
    """Test full loop: Coding -> Validation -> Review (Rejected) -> Rollback."""
    settings.review_enabled = True
    settings.coding_auto_commit = True
    settings.coding_run_validation = False
    
    git_service = GitCLIWorkspaceService(repo_dir)
    registry = ToolRegistry()
    
    class OrchestratedLLM(MockLLMProvider):
        def __init__(self):
            super().__init__()
            self.call_count = 0
            
        async def generate(self, request: Any) -> LLMResponse:
            self.call_count += 1
            if "Review Request" in request.messages[-1].content:
                # Reviewer call
                decision = {
                    "status": "APPROVED",
                    "rationale_summary": "Rejected via finding severity override",
                    "findings": [
                        {
                            "severity": "CRITICAL",
                            "category": "security",
                            "description": "Hardcoded secret",
                            "evidence": "line 1",
                            "recommendation": "remove"
                        }
                    ]
                }
                return LLMResponse(model="mock", content=json.dumps(decision))
            else:
                if self.call_count == 1:
                    return LLMResponse(
                        model="mock", 
                        content=json.dumps({"action": "modify", "rationale_summary": "Implementing", "completion_requested": False})
                    )
                else:
                    (repo_dir / "src" / "main.py").write_text("print('secret=123')\n")
                    return LLMResponse(
                        model="mock",
                        content=json.dumps({"action": "finish", "rationale_summary": "Done", "completion_requested": True})
                    )

    llm = OrchestratedLLM()
    review_agent = ReviewAgent(llm_client=llm, tool_registry=registry)
    agent = CodingAgent(
        llm_client=llm, 
        tool_registry=registry, 
        git_service=git_service,
        review_agent=review_agent
    )
    agent.sandbox_manager = MockSandboxManager()
    
    result = await agent.run(task, plan, repo_dir)
    
    assert result.success is False
    assert result.final_phase == CodingPhase.ROLLED_BACK
    assert "Review rejected" in result.error_message
    
    # Workspace should be rolled back
    status = await git_service.get_status()
    assert status.is_clean is True
    # Verify file contents are restored
    content = (repo_dir / "src" / "main.py").read_text()
    assert content == "print('hello')\n"
