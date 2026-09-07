"""Test Strategy Agent implementation."""

import json

from pydantic import ValidationError

from forgeai.agents.errors import TestStrategyParseError, TestStrategyValidationError
from forgeai.agents.models import (
    EngineeringPlan,
    EngineeringTask,
    TestStrategy,
)
from forgeai.llm.client import LLMClient
from forgeai.llm.models import LLMMessage, LLMRequest
from forgeai.repository.models import RepositorySnapshot


class TestStrategyAgent:
    """Agent responsible for designing the validation strategy for an engineering task."""

    def __init__(self, llm_client: LLMClient) -> None:
        """
        Initialize the test strategy agent.

        Args:
            llm_client: The abstraction for language model communication.
        """
        self.llm = llm_client

    def _build_context(
        self,
        task: EngineeringTask,
        plan: EngineeringPlan,
        snapshot: RepositorySnapshot,
    ) -> str:
        """Build the context prompt for the LLM."""
        context = (
            f"--- ENGINEERING TASK ---\n"
            f"Objective: {task.objective}\n"
            f"Requirements: {task.requirements}\n"
            f"Acceptance Criteria: {task.acceptance_criteria}\n"
            f"Constraints: {task.constraints}\n"
            f"Assumptions: {task.assumptions}\n"
            f"Risk Level: {task.risk_level.value}\n\n"
            f"--- ENGINEERING PLAN ---\n"
            f"Proposed Changes: {plan.proposed_changes}\n"
            f"Affected Files: {plan.affected_files}\n\n"
            f"--- REPOSITORY CONTEXT ---\n"
            f"Test Files Available in Repository:\n"
        )
        if snapshot.test_files:
            for tf in snapshot.test_files:
                context += f"- {tf}\n"
        else:
            context += "(No test files found)\n"

        context += "\nImportant Files:\n"
        for imp in snapshot.important_files:
            context += f"- {imp}\n"

        return context

    def _validate_application_rules(
        self,
        strategy: TestStrategy,
        task: EngineeringTask,
        snapshot: RepositorySnapshot,
    ) -> TestStrategy:
        """
        Apply deterministic application-level validation to the LLM-generated test strategy.
        """
        # 1. Verify acceptance criteria coverage mapping
        if task.acceptance_criteria and not strategy.validation_goals:
            raise TestStrategyValidationError(
                "Task has acceptance criteria, but TestStrategy contains no validation_goals."
            )

        if task.acceptance_criteria and not strategy.test_cases:
            raise TestStrategyValidationError(
                "Task has acceptance criteria, but TestStrategy contains no structured test cases."
            )

        # 2. Verify no fabricated existing tests
        repo_test_files = set(snapshot.test_files)
        for existing_test in strategy.relevant_existing_tests:
            # We allow referencing exact test files, or at least verify it's a known path
            if existing_test not in repo_test_files and not any(
                existing_test in t for t in repo_test_files
            ):
                raise TestStrategyValidationError(
                    f"Fabricated repository fact: LLM claimed '{existing_test}' exists, but it was not found in the repository."
                )

        # 3. Verify validation commands don't bypass policy
        # Basic check: no shell chaining operators
        forbidden_chars = [";", "&&", "||", "|", ">", "<", "`", "$("]
        for cmd in strategy.validation_commands:
            if any(fc in cmd for fc in forbidden_chars):
                raise TestStrategyValidationError(
                    f"Validation command '{cmd}' contains forbidden shell operators."
                )

            # Simple policy: Must start with python, pytest, ruff, mypy, or similar known safe dev tools
            # This is a basic safety mechanism as actual execution is handled elsewhere,
            # but we want to catch LLM hallucinating `rm -rf` here.
            safe_prefixes = ("python", "pytest", "ruff", "mypy", "flake8", "black")
            if not cmd.strip().startswith(safe_prefixes):
                raise TestStrategyValidationError(
                    f"Validation command '{cmd}' does not start with a permitted safe executable."
                )

        return strategy

    async def generate_strategy(
        self,
        task: EngineeringTask,
        plan: EngineeringPlan,
        snapshot: RepositorySnapshot,
    ) -> TestStrategy:
        """
        Generate a validation strategy for the given task and plan.

        Args:
            task: The structured engineering task.
            plan: The structured engineering plan.
            snapshot: A deterministic snapshot of the target codebase.

        Returns:
            A validated TestStrategy.

        Raises:
            TestStrategyParseError: If the model output is malformed or invalid JSON.
            TestStrategyValidationError: If the model output violates deterministic application rules.
            LLMError: If the underlying model provider fails.
        """
        context = self._build_context(task, plan, snapshot)
        schema = TestStrategy.model_json_schema()

        system_prompt = (
            "You are a Senior Test Strategy Agent.\n"
            "Your objective is to reason about how to prove that an engineering task has been implemented correctly.\n\n"
            "CRITICAL RULES:\n"
            "1. NO REPOSITORY MUTATION: You are strictly planning validation, not writing tests.\n"
            "2. DO NOT INVENT EXISTING TESTS: Only classify tests as 'relevant_existing_tests' if they explicitly exist in the repository context.\n"
            "3. EXPLICIT SEPARATION: Clearly distinguish tests that already exist from 'proposed_tests' that need to be created.\n"
            "4. ACCEPTANCE CRITERIA: You MUST map the task's acceptance criteria to specific validation goals and test cases.\n"
            "5. RISK-AWARE: Tailor the strategy to the task's Risk Level.\n"
            "6. VALIDATION COMMANDS: Recommend safe, standard Python commands (e.g., pytest, mypy, ruff) without shell operators.\n"
            "Respond ONLY with a valid JSON object matching this schema:\n"
            f"{json.dumps(schema)}"
        )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="user",
                content=f"Generate a test strategy for the following task:\n\n{context}",
            ),
        ]

        request = LLMRequest(
            messages=messages, temperature=0.1, model="test-strategy-model"
        )

        response = await self.llm.generate(request)

        # Parse output
        try:
            content = response.content or ""
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]

            data = json.loads(content.strip())
            strategy = TestStrategy.model_validate(data)

            # Ensure task ID maps
            strategy.task_id = task.task_id
        except (json.JSONDecodeError, ValidationError) as e:
            raise TestStrategyParseError(f"Failed to parse TestStrategy: {e}") from e

        # Apply deterministic application rules
        validated_strategy = self._validate_application_rules(strategy, task, snapshot)

        return validated_strategy
