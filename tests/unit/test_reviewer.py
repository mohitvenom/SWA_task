import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from forgeai.agents.models import (
    AgentTask,
    EngineeringPlan,
    ReviewDecision,
    ReviewFinding,
    ReviewStatus,
    ReviewSeverity,
)
from forgeai.agents.reviewer import ReviewAgent, ReviewPolicy
from forgeai.git.models import GitDiff, ChangeType
from forgeai.tools.errors import SecurityViolationError
from forgeai.tools.models import ToolCapability

from tests.unit.test_coder import MockLLMProvider


class MockToolDefinition(BaseModel):
    name: str
    capability: ToolCapability


class MockTool(BaseModel):
    definition: MockToolDefinition


def test_review_policy_enforcement():
    # Read only is allowed
    ReviewPolicy.authorize_tool("read_file", ToolCapability.READ_ONLY)
    
    # Anything else is forbidden
    with pytest.raises(SecurityViolationError):
        ReviewPolicy.authorize_tool("write_file", ToolCapability.MUTATION)
    with pytest.raises(SecurityViolationError):
        ReviewPolicy.authorize_tool("run_command", ToolCapability.EXECUTION)


@pytest.fixture
def plan() -> EngineeringPlan:
    return EngineeringPlan(
        plan_id="plan-1",
        task_description="Fix bug",
        task_interpretation="Fix bug",
        proposed_changes="...",
        validation_strategy="...",
        affected_files=["src/main.py"],
        excluded_files=["src/secrets.py"],
        confidence=1.0,
    )


@pytest.fixture
def task() -> AgentTask:
    return AgentTask(task_id="task-1", description="Fix bug")


@pytest.fixture
def empty_diff() -> GitDiff:
    return GitDiff(changed_files=0, insertions=0, deletions=0, patch="")


@pytest.fixture
def mock_registry():
    class MockRegistry:
        def get_openai_schemas(self):
            return []
            
        def get(self, name):
            raise Exception("Tool not found")
            
    return MockRegistry()


@pytest.mark.anyio
async def test_reviewer_approved(task, plan, empty_diff, mock_registry):
    decision = {
        "status": "APPROVED",
        "rationale_summary": "Looks good",
        "findings": [
            {
                "severity": "INFO",
                "category": "style",
                "description": "minor style",
                "evidence": "none",
                "recommendation": "none"
            }
        ]
    }
    llm = MockLLMProvider(default_response=json.dumps(decision))
    agent = ReviewAgent(llm_client=llm, tool_registry=mock_registry)
    
    result = await agent.run(task, plan, empty_diff, [], [], None)
    
    assert result.status == ReviewStatus.APPROVED
    assert len(result.findings) == 1
    assert result.iteration_count == 1


@pytest.mark.anyio
async def test_reviewer_critical_mapping(task, plan, empty_diff, mock_registry):
    # LLM says APPROVED but has a CRITICAL finding
    decision = {
        "status": "APPROVED",
        "rationale_summary": "Looks good but broke everything",
        "findings": [
            {
                "severity": "CRITICAL",
                "category": "security",
                "description": "hardcoded password",
                "evidence": "line 42",
                "recommendation": "remove it"
            }
        ]
    }
    llm = MockLLMProvider(default_response=json.dumps(decision))
    agent = ReviewAgent(llm_client=llm, tool_registry=mock_registry)
    
    result = await agent.run(task, plan, empty_diff, [], [], None)
    
    # Application overrides the status
    assert result.status == ReviewStatus.REJECTED


@pytest.mark.anyio
async def test_reviewer_medium_mapping(task, plan, empty_diff, mock_registry):
    # LLM says APPROVED but has a MEDIUM finding
    decision = {
        "status": "APPROVED",
        "rationale_summary": "Looks good",
        "findings": [
            {
                "severity": "MEDIUM",
                "category": "correctness",
                "description": "missing edge case",
                "evidence": "func(x)",
                "recommendation": "handle it"
            }
        ]
    }
    llm = MockLLMProvider(default_response=json.dumps(decision))
    agent = ReviewAgent(llm_client=llm, tool_registry=mock_registry)
    
    result = await agent.run(task, plan, empty_diff, [], [], None)
    
    # Application overrides the status
    assert result.status == ReviewStatus.CHANGES_REQUIRED


@pytest.mark.anyio
async def test_reviewer_malformed_output(task, plan, empty_diff, mock_registry):
    llm = MockLLMProvider(default_response="{ invalid json }")
    agent = ReviewAgent(llm_client=llm, tool_registry=mock_registry)
    # The agent will retry max_tool_calls times if the output is malformed, then fail.
    agent.max_tool_calls = 2
    
    result = await agent.run(task, plan, empty_diff, [], [], None)
    
    # Should reject on exhaustion
    assert result.status == ReviewStatus.REJECTED
    assert "exhausted tool iterations" in result.error_message
