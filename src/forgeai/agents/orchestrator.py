"""Agent orchestrator implementation."""

import json
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from forgeai.agents.errors import (
    AgentDecisionParseError,
    AgentMaxIterationsError,
    AgentStateTransitionError,
)
from forgeai.agents.models import (
    AgentDecision,
    AgentResult,
    AgentSession,
    AgentState,
    AgentStep,
)
from forgeai.agents.state import StateMachine
from forgeai.config.settings import settings
from forgeai.llm.client import LLMClient
from forgeai.llm.errors import LLMError
from forgeai.llm.models import LLMMessage, LLMRequest, LLMToolCall
from forgeai.tools.errors import SecurityViolationError
from forgeai.tools.models import ToolCall, ToolContext
from forgeai.tools.registry import ToolRegistry


class AgentOrchestrator:
    """Orchestrates agent execution using an LLMClient and ToolRegistry."""

    # Allowed read-only capabilities for Phase 7
    ALLOWED_TOOLS = {"list_files", "read_file", "search_code"}

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry | None = None,
        tool_context: ToolContext | None = None,
    ) -> None:
        """
        Initialize the orchestrator.

        Args:
            llm_client: The LLM client adapter to use for inference.
            tool_registry: The registry containing available tools.
            tool_context: The execution context for tools (workspace root).
        """
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.tool_context = tool_context
        self.max_iterations = settings.agent_max_iterations
        self.messages: list[LLMMessage] = []

    def _create_step(self, session: AgentSession, state: AgentState) -> AgentStep:
        return AgentStep(
            step_id=str(uuid.uuid4()),
            sequence=len(session.steps) + 1,
            state=state,
            start_time=datetime.now(timezone.utc),
        )

    def _transition_to(self, session: AgentSession, next_state: AgentState) -> None:
        StateMachine.validate_transition(session.current_state, next_state)
        session.current_state = next_state
        session.updated_at = datetime.now(timezone.utc)

    async def _execute_tool_calls(
        self, session: AgentSession, tool_calls: list[LLMToolCall], step: AgentStep
    ) -> None:
        """Execute a list of tool calls and append results to history."""
        self._transition_to(session, AgentState.TOOL_EXECUTING)
        step.state = AgentState.TOOL_EXECUTING

        for llm_tc in tool_calls:
            # Check capability policy
            if llm_tc.name not in self.ALLOWED_TOOLS:
                err_msg = f"Security Violation: Tool '{llm_tc.name}' is not permitted."
                self.messages.append(
                    LLMMessage(
                        role="tool",
                        tool_call_id=llm_tc.id,
                        content=json.dumps({"error": err_msg}),
                    )
                )
                continue

            # Ensure registry and context are present
            if not self.tool_registry or not self.tool_context:
                self.messages.append(
                    LLMMessage(
                        role="tool",
                        tool_call_id=llm_tc.id,
                        content=json.dumps(
                            {"error": "Tool execution environment not configured."}
                        ),
                    )
                )
                continue

            # Retrieve tool
            try:
                tool = self.tool_registry.get(llm_tc.name)
            except Exception as e:
                self.messages.append(
                    LLMMessage(
                        role="tool",
                        tool_call_id=llm_tc.id,
                        content=json.dumps({"error": f"Unknown tool: {e}"}),
                    )
                )
                continue

            # Execute tool
            call = ToolCall(
                call_id=llm_tc.id, name=llm_tc.name, arguments=llm_tc.arguments
            )
            try:
                result = await tool.execute(call, self.tool_context)
                if result.success:
                    payload = {"result": result.output}
                else:
                    payload = {"error": result.error}
            except SecurityViolationError as e:
                # Hard failure for security bounds like path traversal
                raise e
            except Exception as e:
                payload = {"error": f"Tool execution failed: {e}"}

            self.messages.append(
                LLMMessage(
                    role="tool",
                    tool_call_id=llm_tc.id,
                    content=json.dumps(payload),
                )
            )

        self._transition_to(session, AgentState.THINKING)
        step.state = AgentState.THINKING

    async def _run_iteration(
        self, session: AgentSession, step: AgentStep
    ) -> AgentDecision | None:
        """Run a single iteration of the LLM interaction."""
        schemas = []
        if self.tool_registry:
            schemas = [
                s
                for s in self.tool_registry.get_openai_schemas()
                if s["function"]["name"] in self.ALLOWED_TOOLS
            ]

        request = LLMRequest(
            model=settings.omniroute_default_model, messages=self.messages, temperature=0.0, tools=schemas
        )
        response = await self.llm_client.generate(request)

        # Append assistant response
        self.messages.append(
            LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
        )

        if response.tool_calls:
            step.metadata["tool_calls"] = [
                {"id": tc.id, "name": tc.name} for tc in response.tool_calls
            ]
            await self._execute_tool_calls(session, response.tool_calls, step)
            return None  # Need another iteration to interpret results

        # No tool calls; try to parse final decision
        try:
            content = response.content or ""
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]

            data = json.loads(content.strip())
            return AgentDecision.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            # If the model fails to return JSON when no tool calls are made,
            # we return a parse error message to it, or we just fail.
            # The requirement: "A tool failure should NOT automatically crash.
            # Handle at least: malformed LLM response."
            # We raise the error to fail the step if it's the final output.
            raise AgentDecisionParseError(f"Failed to parse AgentDecision: {e}") from e

    async def run(self, session: AgentSession) -> AgentResult:
        """
        Execute the agent session until completion, failure, or iteration limit.

        Args:
            session: The agent session to execute.

        Returns:
            The final AgentResult containing the session state and outcome.
        """
        schema = AgentDecision.model_json_schema()
        system_prompt = (
            "You are an autonomous agent capable of using read-only tools to "
            "investigate the repository. Use tools to gather information as needed. "
            "Once you have sufficient information, or if no tools are needed, you "
            "MUST return ONLY a valid JSON object matching this schema:\n"
            f"{json.dumps(schema)}"
        )
        self.messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="user",
                content=f"Determine the next step for task: {session.task_id}",
            ),
        ]

        try:
            if session.current_state == AgentState.PENDING:
                self._transition_to(session, AgentState.RUNNING)

            while session.current_state in (AgentState.RUNNING, AgentState.THINKING):
                if session.iteration_count >= self.max_iterations:
                    raise AgentMaxIterationsError(
                        f"Exceeded max iterations: {self.max_iterations}"
                    )

                session.iteration_count += 1

                if session.current_state == AgentState.RUNNING:
                    self._transition_to(session, AgentState.THINKING)

                step = self._create_step(session, AgentState.THINKING)

                try:
                    decision = await self._run_iteration(session, step)

                    if decision:
                        step.metadata["decision"] = decision.model_dump(mode="json")
                        self._transition_to(session, decision.next_state)
                        step.success = True
                        step.end_time = datetime.now(timezone.utc)
                        session.steps.append(step)
                        break
                    else:
                        # Tools were executed, continue loop
                        step.success = True
                        step.end_time = datetime.now(timezone.utc)
                        session.steps.append(step)

                except SecurityViolationError as e:
                    # Hard failure
                    step.success = False
                    step.metadata["error"] = f"Security Violation: {e}"
                    self._transition_to(session, AgentState.FAILED)
                    session.steps.append(step)
                    step.end_time = datetime.now(timezone.utc)
                    return AgentResult(
                        success=False,
                        final_state=AgentState.FAILED,
                        session=session,
                        error_message=str(e),
                    )
                except (
                    LLMError,
                    AgentDecisionParseError,
                    AgentStateTransitionError,
                ) as e:
                    step.success = False
                    step.metadata["error"] = str(e)
                    self._transition_to(session, AgentState.FAILED)
                    session.steps.append(step)
                    step.end_time = datetime.now(timezone.utc)
                    return AgentResult(
                        success=False,
                        final_state=AgentState.FAILED,
                        session=session,
                        error_message=str(e),
                    )

            is_success = session.current_state == AgentState.COMPLETED
            return AgentResult(
                success=is_success,
                final_state=session.current_state,
                session=session,
                error_message=None
                if is_success
                else f"Ended in state {session.current_state.value}",
            )

        except Exception as e:
            try:
                self._transition_to(session, AgentState.FAILED)
            except AgentStateTransitionError:
                session.current_state = AgentState.FAILED
            return AgentResult(
                success=False,
                final_state=AgentState.FAILED,
                session=session,
                error_message=str(e),
            )
