"""Independent Code Review and Final Validation Agent."""

import json
from typing import Any

from pydantic import ValidationError

from forgeai.agents.errors import AgentDecisionParseError
from forgeai.agents.models import (
    AgentTask,
    EngineeringPlan,
    ReviewDecision,
    ReviewResult,
    ReviewStatus,
    ReviewFinding,
)
from forgeai.git.models import GitDiff
from forgeai.llm.client import LLMClient
from forgeai.llm.models import LLMMessage, LLMRequest, LLMToolCall
from forgeai.tools.errors import SecurityViolationError
from forgeai.tools.models import ToolCall, ToolCapability, ToolContext
from forgeai.tools.registry import ToolRegistry


class ReviewPolicy:
    """Authorization policy for the Review Agent."""

    @staticmethod
    def authorize_tool(tool_name: str, capability: ToolCapability) -> None:
        """Ensure only read-only tools are used."""
        if capability != ToolCapability.READ_ONLY:
            raise SecurityViolationError(
                f"ReviewAgent is restricted to READ_ONLY capabilities. Tool '{tool_name}' ({capability}) is forbidden."
            )


class ReviewAgent:
    """An independent agent that reviews CodingAgent changes against the EngineeringPlan."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.messages: list[LLMMessage] = []
        self.max_tool_calls = 20

    def _get_system_prompt(self, plan: EngineeringPlan) -> str:
        schema = ReviewDecision.model_json_schema()
        return (
            "You are an independent senior software engineer. Your task is to review the code changes "
            "made by another agent. You must act as the final authority on correctness, security, "
            "and plan compliance. You MUST NOT blindly trust that the code is correct.\n\n"
            "Review Scope:\n"
            "1. Plan Compliance: Does the implementation address the objective? Were only authorized files changed?\n"
            "2. Correctness: Are there logical errors?\n"
            "3. Security: Are boundaries respected? No shell injection? No exposed secrets?\n"
            "4. Regression Risk: Could this break existing functionality?\n"
            "5. Test Coverage: Are adequate tests present for the changes?\n\n"
            "Constraints:\n"
            "- You have READ-ONLY tools available to explore the workspace if you need context beyond the diff.\n"
            "- You CANNOT mutate files. Do not ask for edit capabilities.\n"
            "- Do not nitpick stylistic choices unless they violate the project's strict typing rules (e.g., using `Any`).\n"
            "- Provide actionable, specific evidence for any finding.\n\n"
            f"Engineering Plan Objective: {plan.task_interpretation}\n"
            f"Authorized Affected Files: {plan.affected_files}\n"
            f"Excluded Files: {plan.excluded_files}\n\n"
            "Decision Schema:\n"
            f"{json.dumps(schema)}"
        )

    async def _execute_tool_calls(
        self,
        tool_calls: list[LLMToolCall],
        context: ToolContext,
    ) -> None:
        """Execute read-only tool calls."""
        for llm_tc in tool_calls:
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

            try:
                ReviewPolicy.authorize_tool(tool.definition.name, tool.definition.capability)

                call = ToolCall(
                    call_id=llm_tc.id, name=llm_tc.name, arguments=llm_tc.arguments
                )
                result = await tool.execute(call, context)

                output_str = str(result.output) if result.success else str(result.error)
                # truncate output to prevent context blowout (4096 is standard)
                if len(output_str) > 4096:
                    output_str = output_str[:4096] + "... (truncated)"

                payload = {"result": output_str} if result.success else {"error": output_str}
            except SecurityViolationError as e:
                payload = {"error": f"Security Violation: {e}"}
            except Exception as e:
                payload = {"error": f"Tool execution failed: {e}"}

            self.messages.append(
                LLMMessage(
                    role="tool",
                    tool_call_id=llm_tc.id,
                    content=json.dumps(payload),
                )
            )

    async def _run_iteration(
        self,
        context: ToolContext,
    ) -> ReviewDecision | None:
        """Run a single LLM iteration."""
        schemas = self.tool_registry.get_openai_schemas()

        request = LLMRequest(
            model="default",
            messages=self.messages,
            temperature=0.0,
            tools=schemas,
        )
        response = await self.llm_client.generate(request)

        self.messages.append(
            LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
        )

        if response.tool_calls:
            await self._execute_tool_calls(response.tool_calls, context)
            return None

        # Parse decision
        try:
            content = response.content or ""
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]

            data = json.loads(content.strip())
            return ReviewDecision.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise AgentDecisionParseError(f"Failed to parse ReviewDecision: {e}") from e

    def _evaluate_findings(self, decision: ReviewDecision) -> ReviewStatus:
        """
        Evaluate findings deterministically to override the LLM if necessary.
        
        CRITICAL -> REJECTED
        HIGH -> CHANGES_REQUIRED or REJECTED
        MEDIUM -> CHANGES_REQUIRED
        LOW/INFO -> APPROVED (or as decided by LLM, but at worst CHANGES_REQUIRED)
        """
        has_critical = any(f.severity == "CRITICAL" for f in decision.findings)
        has_high = any(f.severity == "HIGH" for f in decision.findings)
        has_medium = any(f.severity == "MEDIUM" for f in decision.findings)

        if has_critical:
            return ReviewStatus.REJECTED
        if has_high:
            # If the LLM didn't already reject, force it to at least CHANGES_REQUIRED.
            if decision.status != ReviewStatus.REJECTED:
                return ReviewStatus.CHANGES_REQUIRED
        if has_medium:
            if decision.status == ReviewStatus.APPROVED:
                return ReviewStatus.CHANGES_REQUIRED
                
        return decision.status

    async def run(
        self,
        task: AgentTask,
        plan: EngineeringPlan,
        diff: GitDiff,
        changed_files: list[str],
        validation_results: list[dict[str, Any]],
        context: ToolContext,
    ) -> ReviewResult:
        """Execute the review cycle."""
        
        plan_compliance = True
        
        # Prepare context for LLM
        validation_str = json.dumps(validation_results, indent=2)
        diff_str = diff.patch
        if not diff_str.strip():
            diff_str = "No changes detected."

        prompt_content = (
            f"Review Request for Task: {task.task_id}\n\n"
            f"Validation Results:\n{validation_str}\n\n"
            f"Changed Files (Application Verified):\n{changed_files}\n\n"
            f"Git Diff:\n{diff_str}\n\n"
            "Please review the above changes, utilize tools to inspect the broader context if needed, "
            "and output your final ReviewDecision JSON."
        )

        self.messages = [
            LLMMessage(role="system", content=self._get_system_prompt(plan)),
            LLMMessage(role="user", content=prompt_content),
        ]

        iteration = 0
        while iteration < self.max_tool_calls:
            iteration += 1
            try:
                decision = await self._run_iteration(context)
            except AgentDecisionParseError as e:
                self.messages.append(
                    LLMMessage(
                        role="user",
                        content=f"Error parsing decision: {e}. Please respond with valid JSON.",
                    )
                )
                continue

            if decision:
                # Deterministically override status based on severities
                final_status = self._evaluate_findings(decision)
                
                return ReviewResult(
                    status=final_status,
                    findings=decision.findings,
                    reviewed_files=changed_files,
                    iteration_count=iteration,
                    plan_compliance=plan_compliance,
                    validation_summary=decision.rationale_summary,
                )

        # Exhausted tool calls without a decision
        return ReviewResult(
            status=ReviewStatus.REJECTED,
            plan_compliance=False,
            error_message="Reviewer exhausted tool iterations without making a decision.",
        )
