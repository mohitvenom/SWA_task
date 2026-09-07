from unittest.mock import AsyncMock, MagicMock

import pytest

from forgeai.agents.errors import TaskIntelligenceParseError
from forgeai.agents.models import (
    AmbiguitySeverity,
    TaskIntelligenceStatus,
)
from forgeai.agents.task_intelligence import TaskIntelligenceAgent
from forgeai.llm.client import LLMClient
from forgeai.llm.errors import LLMError
from forgeai.llm.models import LLMResponse


@pytest.fixture
def mock_llm() -> LLMClient:
    llm = MagicMock(spec=LLMClient)
    llm.generate = AsyncMock()
    return llm


@pytest.fixture
def agent(mock_llm: LLMClient) -> TaskIntelligenceAgent:
    return TaskIntelligenceAgent(llm_client=mock_llm)


@pytest.mark.anyio
async def test_analyze_simple_clear_task(
    agent: TaskIntelligenceAgent, mock_llm: MagicMock
) -> None:
    mock_llm.generate.return_value = LLMResponse(
        content='{"objective": "Add a multiply function to calculator.py.", "original_request": ""}',
        model="test",
    )

    result = await agent.analyze("Add a multiply function to calculator.py.")

    assert result.status == TaskIntelligenceStatus.READY
    assert result.objective == "Add a multiply function to calculator.py."
    assert result.original_request == "Add a multiply function to calculator.py."


@pytest.mark.anyio
async def test_analyze_blocking_ambiguity(
    agent: TaskIntelligenceAgent, mock_llm: MagicMock
) -> None:
    # LLM returns READY but with a BLOCKING ambiguity. The agent must correct it to NEEDS_CLARIFICATION.
    mock_llm.generate.return_value = LLMResponse(
        content="""{
            "objective": "Delete the old authentication system.",
            "original_request": "",
            "ambiguities": [
                {"question": "Which authentication system is the old one?", "severity": "BLOCKING"}
            ],
            "status": "READY"
        }""",
        model="test",
    )

    result = await agent.analyze("Delete the old authentication system.")

    # Application validation rule should override READY to NEEDS_CLARIFICATION
    assert result.status == TaskIntelligenceStatus.NEEDS_CLARIFICATION
    assert len(result.ambiguities) == 1
    assert result.ambiguities[0].severity == AmbiguitySeverity.BLOCKING


@pytest.mark.anyio
async def test_analyze_malformed_llm_response(
    agent: TaskIntelligenceAgent, mock_llm: MagicMock
) -> None:
    mock_llm.generate.return_value = LLMResponse(
        content="This is not valid JSON.",
        model="test",
    )

    with pytest.raises(TaskIntelligenceParseError):
        await agent.analyze("Do something.")


@pytest.mark.anyio
async def test_analyze_llm_failure(
    agent: TaskIntelligenceAgent, mock_llm: MagicMock
) -> None:
    mock_llm.generate.side_effect = LLMError("API Down")

    with pytest.raises(LLMError):
        await agent.analyze("Do something.")
