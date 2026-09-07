"""Unit tests for the agent orchestration layer."""

import json
from pathlib import Path

import pytest

from forgeai.agents.models import AgentSession, AgentState
from forgeai.agents.orchestrator import AgentOrchestrator
from forgeai.llm.models import LLMRequest, LLMResponse, LLMToolCall
from forgeai.llm.providers.mock import MockLLMProvider
from forgeai.tools.base import BaseTool
from forgeai.tools.errors import SecurityViolationError, ToolExecutionError
from forgeai.tools.models import ToolCall, ToolContext, ToolDefinition, ToolResult
from forgeai.tools.registry import ToolRegistry
from forgeai.tools.repository.write_file import WriteFileTool


class DummyTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_code",
            description="Search code.",
            input_schema={},
        )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        if call.arguments.get("fail"):
            raise ToolExecutionError("Mock tool execution failure")
        return ToolResult(call_id=call.call_id, success=True, output={"results": []})


class DummyListTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_files",
            description="List files.",
            input_schema={},
        )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        return ToolResult(
            call_id=call.call_id, success=True, output={"files": ["main.py"]}
        )


class DummyReadTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description="Read file.",
            input_schema={},
        )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        return ToolResult(
            call_id=call.call_id, success=True, output={"content": "code"}
        )


class EvilTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(name="evil", description="evil", input_schema={})

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        raise SecurityViolationError("Path traversal")


@pytest.fixture
def mock_session() -> AgentSession:
    return AgentSession(session_id="sess-1", task_id="task-1")


@pytest.fixture
def orchestrator() -> AgentOrchestrator:
    registry = ToolRegistry()
    registry.register(DummyTool())
    registry.register(DummyListTool())
    registry.register(DummyReadTool())
    registry.register(EvilTool())
    registry.register(WriteFileTool())
    context = ToolContext(workspace_root=Path("/mock"))
    provider = MockLLMProvider()
    return AgentOrchestrator(
        llm_client=provider, tool_registry=registry, tool_context=context
    )


@pytest.mark.anyio
async def test_orchestrator_success_no_tools(
    mock_session: AgentSession, orchestrator: AgentOrchestrator
) -> None:
    decision = {
        "decision": "I have finished the task",
        "rationale": "Task is complete.",
        "confidence": 1.0,
        "next_state": "COMPLETED",
        "data": {},
    }
    orchestrator.llm_client = MockLLMProvider(default_response=json.dumps(decision))
    result = await orchestrator.run(mock_session)

    assert result.success is True
    assert result.final_state == AgentState.COMPLETED
    assert result.session.iteration_count == 1


@pytest.mark.anyio
async def test_orchestrator_one_tool_then_finish(
    mock_session: AgentSession, orchestrator: AgentOrchestrator
) -> None:
    call_count = 0

    def factory(req: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                model="mock",
                tool_calls=[LLMToolCall(id="1", name="search_code", arguments={})],
            )
        else:
            assert any(m.role == "tool" and m.tool_call_id == "1" for m in req.messages)
            decision = {
                "decision": "I have finished the task",
                "rationale": "Task is complete.",
                "confidence": 1.0,
                "next_state": "COMPLETED",
                "data": {},
            }
            return LLMResponse(content=json.dumps(decision), model="mock")

    orchestrator.llm_client = MockLLMProvider(response_factory=factory)
    result = await orchestrator.run(mock_session)

    assert result.success is True
    assert call_count == 2
    assert any("tool_calls" in s.metadata for s in result.session.steps)


@pytest.mark.anyio
async def test_orchestrator_multiple_tools_concurrent(
    mock_session: AgentSession, orchestrator: AgentOrchestrator
) -> None:
    call_count = 0

    def factory(req: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(id="1", name="search_code", arguments={}),
                    LLMToolCall(id="2", name="list_files", arguments={}),
                ],
            )
        else:
            assert len([m for m in req.messages if m.role == "tool"]) == 2
            decision = {
                "decision": "Done",
                "rationale": "Done.",
                "confidence": 1.0,
                "next_state": "COMPLETED",
                "data": {},
            }
            return LLMResponse(content=json.dumps(decision), model="mock")

    orchestrator.llm_client = MockLLMProvider(response_factory=factory)
    result = await orchestrator.run(mock_session)
    assert result.success is True


@pytest.mark.anyio
async def test_orchestrator_unknown_tool_rejection(
    mock_session: AgentSession, orchestrator: AgentOrchestrator
) -> None:
    call_count = 0

    def factory(req: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                model="mock",
                tool_calls=[LLMToolCall(id="1", name="list_files", arguments={})],
            )  # Allowed tool
        elif call_count == 2:
            return LLMResponse(
                model="mock",
                tool_calls=[LLMToolCall(id="2", name="nonexistent_tool", arguments={})],
            )  # Not allowed
        else:
            assert any(
                "Security Violation: Tool 'nonexistent_tool' is not permitted"
                in m.content
                for m in req.messages
                if m.role == "tool" and m.content
            )
            decision = {
                "decision": "Done",
                "rationale": "Done.",
                "confidence": 1.0,
                "next_state": "COMPLETED",
                "data": {},
            }
            return LLMResponse(content=json.dumps(decision), model="mock")

    orchestrator.llm_client = MockLLMProvider(response_factory=factory)
    result = await orchestrator.run(mock_session)
    assert result.success is True


@pytest.mark.anyio
async def test_orchestrator_mutation_tool_rejection(
    mock_session: AgentSession, orchestrator: AgentOrchestrator
) -> None:
    """Prove that an LLM-requested write_file call is rejected by the "
    "capability policy."""
    call_count = 0

    def factory(req: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="1",
                        name="write_file",
                        arguments={"path": "test.txt", "content": "hello"},
                    )
                ],
            )
        else:
            assert any(
                "Security Violation: Tool 'write_file' is not permitted" in m.content
                for m in req.messages
                if m.role == "tool" and m.content
            )
            decision = {
                "decision": "Done",
                "rationale": "Done.",
                "confidence": 1.0,
                "next_state": "COMPLETED",
                "data": {},
            }
            return LLMResponse(content=json.dumps(decision), model="mock")

    orchestrator.llm_client = MockLLMProvider(response_factory=factory)
    result = await orchestrator.run(mock_session)
    assert result.success is True


@pytest.mark.anyio
async def test_orchestrator_tool_execution_failure(
    mock_session: AgentSession, orchestrator: AgentOrchestrator
) -> None:
    call_count = 0

    def factory(req: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(id="1", name="search_code", arguments={"fail": True})
                ],
            )
        else:
            assert any(
                "Mock tool execution failure" in m.content
                for m in req.messages
                if m.role == "tool" and m.content
            )
            decision = {
                "decision": "Done",
                "rationale": "Done.",
                "confidence": 1.0,
                "next_state": "COMPLETED",
                "data": {},
            }
            return LLMResponse(content=json.dumps(decision), model="mock")

    orchestrator.llm_client = MockLLMProvider(response_factory=factory)
    result = await orchestrator.run(mock_session)
    assert result.success is True


@pytest.mark.anyio
async def test_orchestrator_security_violation_halts(
    mock_session: AgentSession, orchestrator: AgentOrchestrator
) -> None:
    # Temporarily allow 'evil' to test SecurityViolationError handling
    orchestrator.ALLOWED_TOOLS.add("evil")

    def factory(req: LLMRequest) -> LLMResponse:
        return LLMResponse(
            model="mock", tool_calls=[LLMToolCall(id="1", name="evil", arguments={})]
        )

    orchestrator.llm_client = MockLLMProvider(response_factory=factory)
    result = await orchestrator.run(mock_session)

    assert result.success is False
    assert result.final_state == AgentState.FAILED
    assert "Path traversal" in str(result.error_message)


@pytest.mark.anyio
async def test_orchestrator_max_iterations(
    mock_session: AgentSession, orchestrator: AgentOrchestrator
) -> None:
    orchestrator.max_iterations = 2

    def factory(req: LLMRequest) -> LLMResponse:
        # Infinite loop
        return LLMResponse(
            model="mock",
            tool_calls=[LLMToolCall(id="1", name="search_code", arguments={})],
        )

    orchestrator.llm_client = MockLLMProvider(response_factory=factory)
    result = await orchestrator.run(mock_session)

    assert result.success is False
    assert result.final_state == AgentState.FAILED
    assert "Exceeded max iterations: 2" in result.error_message


@pytest.mark.anyio
async def test_orchestrator_malformed_json_failure(
    mock_session: AgentSession, orchestrator: AgentOrchestrator
) -> None:
    orchestrator.llm_client = MockLLMProvider(default_response="Not JSON")
    result = await orchestrator.run(mock_session)

    assert result.success is False
    assert result.final_state == AgentState.FAILED
    assert "Failed to parse AgentDecision" in result.error_message


@pytest.mark.anyio
async def test_e2e_investigation_scenario(
    mock_session: AgentSession, orchestrator: AgentOrchestrator
) -> None:
    """E2E Test: Find where users API is implemented and identify tests."""
    call_count = 0

    def factory(req: LLMRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-1", name="search_code", arguments={"query": "users API"}
                    )
                ],
            )
        elif call_count == 2:
            assert any(m.tool_call_id == "tc-1" for m in req.messages)
            return LLMResponse(
                model="mock",
                tool_calls=[
                    LLMToolCall(
                        id="tc-2", name="read_file", arguments={"path": "src/users.py"}
                    )
                ],
            )
        elif call_count == 3:
            assert any(m.tool_call_id == "tc-2" for m in req.messages)
            decision = {
                "decision": "I have found the API implementation and tests.",
                "rationale": "It is in src/users.py and tested in tests/test_users.py.",
                "confidence": 1.0,
                "next_state": "COMPLETED",
                "data": {},
            }
            return LLMResponse(content=json.dumps(decision), model="mock")

        raise RuntimeError("Too many calls")

    orchestrator.llm_client = MockLLMProvider(response_factory=factory)
    result = await orchestrator.run(mock_session)

    assert result.success is True
    assert result.session.iteration_count == 3
    assert call_count == 3
