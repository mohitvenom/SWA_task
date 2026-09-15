"""Failure Diagnosis Agent implementation."""

import json
import uuid
from typing import Any

from pydantic import ValidationError

from forgeai.agents.errors import (
    FailureDiagnosisParseError,
    RepairPlanValidationError,
)
from forgeai.agents.models import (
    DiagnosisStatus,
    EngineeringPlan,
    EngineeringTask,
    FailureCategory,
    FailureDiagnosis,
    FailureSeverity,
    TestStrategy,
)
from forgeai.llm.client import LLMClient
from forgeai.llm.models import LLMMessage, LLMRequest
from forgeai.memory.models import MemoryContext
from forgeai.config.settings import settings


class FailureDiagnosisAgent:
    """Agent responsible for diagnosing validation failures and proposing a structured repair plan."""

    def __init__(self, llm_client: LLMClient) -> None:
        """
        Initialize the failure diagnosis agent.

        Args:
            llm_client: The abstraction for language model communication.
        """
        self.llm = llm_client
        self.max_evidence_length = 5000  # Bound evidence

    def _build_context(
        self,
        task: EngineeringTask,
        plan: EngineeringPlan,
        strategy: TestStrategy | None,
        validation_results: list[dict[str, Any]],
        changed_files: list[str],
    ) -> str:
        """Build the context prompt for the LLM."""
        context = (
            f"--- ENGINEERING TASK ---\n"
            f"Objective: {task.objective}\n"
            f"Requirements: {task.requirements}\n"
            f"Acceptance Criteria: {task.acceptance_criteria}\n\n"
            f"--- ENGINEERING PLAN ---\n"
            f"Affected Files: {plan.affected_files}\n"
            f"Excluded Files: {plan.excluded_files}\n\n"
        )
        
        if strategy:
            context += (
                f"--- TEST STRATEGY ---\n"
                f"Validation Goals: {strategy.validation_goals}\n\n"
            )

        context += f"--- IMPLEMENTED CHANGES ---\nChanged Files: {changed_files}\n\n"

        context += "--- VALIDATION EVIDENCE ---\n"
        for idx, result in enumerate(validation_results):
            evidence = str(result)
            if len(evidence) > self.max_evidence_length:
                evidence = evidence[:self.max_evidence_length] + "\n...[TRUNCATED]"
            context += f"Result {idx + 1}:\n{evidence}\n\n"

        return context

    def _validate_application_rules(
        self,
        diagnosis: FailureDiagnosis,
        plan: EngineeringPlan,
    ) -> FailureDiagnosis:
        """
        Apply deterministic application-level validation to the LLM-generated diagnosis and repair plan.
        """
        if diagnosis.category == FailureCategory.ENVIRONMENT_ERROR:
            diagnosis.status = DiagnosisStatus.INFRASTRUCTURE_FAILURE
            diagnosis.repair_plan = None
            return diagnosis

        if diagnosis.repair_plan:
            # Validate proposed actions
            if not diagnosis.repair_plan.proposed_actions:
                raise RepairPlanValidationError("Repair plan must contain at least one proposed action.")
            
            if len(diagnosis.repair_plan.proposed_actions) > 10:
                raise RepairPlanValidationError("Too many repair actions proposed.")

            for action in diagnosis.repair_plan.proposed_actions:
                # Check bounds
                if not any(action.target_file == aff or action.target_file.startswith(aff + "/") for aff in plan.affected_files) and action.target_file not in plan.affected_files:
                    # Stricter check
                    is_affected = False
                    for aff in plan.affected_files:
                        if action.target_file == aff or action.target_file.startswith(aff):
                            is_affected = True
                            break
                    if not is_affected:
                        raise RepairPlanValidationError(
                            f"Target file '{action.target_file}' is not within authorized affected_files."
                        )

                # Check exclusions
                for excl in plan.excluded_files:
                    if action.target_file == excl or action.target_file.startswith(excl):
                        raise RepairPlanValidationError(
                            f"Target file '{action.target_file}' is explicitly excluded."
                        )
                
                # Check for arbitrary embedded shell commands
                forbidden_chars = [";", "&&", "||", "|", "`", "$("]
                if any(fc in action.rationale or fc in action.expected_effect for fc in forbidden_chars):
                    raise RepairPlanValidationError("Arbitrary shell execution detected in repair rationale.")
                    
                bad_words = ["python -c", "bash -c", "sh -c"]
                if any(bw in action.rationale.lower() for bw in bad_words):
                    raise RepairPlanValidationError("Arbitrary shell execution detected in repair rationale.")

        return diagnosis

    async def diagnose(
        self,
        task: EngineeringTask,
        plan: EngineeringPlan,
        strategy: TestStrategy | None,
        validation_results: list[dict[str, Any]],
        changed_files: list[str],
        memory_context: MemoryContext | None = None,
    ) -> FailureDiagnosis:
        """
        Diagnose a validation failure and propose a structured repair plan.

        Args:
            task: The engineering task.
            plan: The engineering plan.
            strategy: The optional test strategy.
            validation_results: The deterministic results of validation.
            changed_files: Files that were mutated in the implementation phase.

        Returns:
            A validated FailureDiagnosis containing an optional RepairPlan.
        """
        # Quick heuristic for infrastructure failure to bypass LLM if obviously infra
        str_results = str(validation_results).lower()
        if "docker unavailable" in str_results or "no running event loop" in str_results:
            return FailureDiagnosis(
                failure_id=str(uuid.uuid4()),
                category=FailureCategory.ENVIRONMENT_ERROR,
                severity=FailureSeverity.CRITICAL,
                symptom_summary="Infrastructure failed to execute validation tools.",
                root_cause_analysis="Test runner or Docker environment is unhealthy.",
                confidence=1.0,
                status=DiagnosisStatus.INFRASTRUCTURE_FAILURE,
            )

        context = self._build_context(task, plan, strategy, validation_results, changed_files)
        schema = FailureDiagnosis.model_json_schema()

        system_prompt = (
            "You are a Senior Failure Diagnosis Agent.\n"
            "Your objective is to reason about why validation failed and propose a controlled repair plan.\n\n"
            "CRITICAL RULES:\n"
            "1. NO DIRECT MUTATION: You are strictly planning repair, not writing code.\n"
            "2. EVIDENCE-BASED: Diagnose ONLY from the supplied Validation Evidence. Do not invent stack traces or test results.\n"
            "3. ROOT CAUSE VS SYMPTOM: Explicitly separate the observed symptom from the underlying root cause.\n"
            "4. INFRASTRUCTURE: If the validation harness failed (e.g., Docker error, timeout), classify as ENVIRONMENT_ERROR.\n"
            "5. REPAIR PLAN: Output a targeted repair plan if the failure is in the code. It MUST stay within 'Affected Files'.\n"
            "6. UNCERTAINTY: Set confidence appropriately (0.0 - 1.0).\n"
            "Respond ONLY with a valid JSON object matching this schema:\n"
            f"{json.dumps(schema)}"
        )

        user_prompt_parts = [f"Diagnose the following validation failure:\n\n{context}"]
        if memory_context:
            user_prompt_parts.append(memory_context.to_structured_string())

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="user",
                content="\n\n".join(user_prompt_parts),
            ),
        ]

        request = LLMRequest(messages=messages, temperature=0.1, model=settings.omniroute_default_model)
        
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
            # Inject an ID if not generated by LLM reliably
            if "failure_id" not in data:
                data["failure_id"] = str(uuid.uuid4())

            diagnosis = FailureDiagnosis.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise FailureDiagnosisParseError(f"Failed to parse FailureDiagnosis: {e}") from e

        # Apply deterministic application rules
        validated_diagnosis = self._validate_application_rules(diagnosis, plan)

        return validated_diagnosis
