"""Task Intelligence Agent implementation for ForgeAI."""

import json
import uuid

from pydantic import ValidationError

from forgeai.agents.errors import TaskIntelligenceParseError
from forgeai.agents.models import (
    AmbiguitySeverity,
    EngineeringTask,
    TaskIntelligenceStatus,
)
from forgeai.llm.client import LLMClient
from forgeai.llm.models import LLMMessage, LLMRequest


class TaskIntelligenceAgent:
    """Agent responsible for analyzing raw user requests to extract structured engineering intent."""

    def __init__(self, llm_client: LLMClient) -> None:
        """
        Initialize the task intelligence agent.

        Args:
            llm_client: The abstraction for language model communication.
        """
        self.llm = llm_client

    def _validate_application_rules(self, task: EngineeringTask) -> EngineeringTask:
        """
        Enforce application-level deterministic rules on the parsed task.
        """
        # Rule: A BLOCKING ambiguity cannot result in READY status.
        has_blocking = any(
            amb.severity == AmbiguitySeverity.BLOCKING for amb in task.ambiguities
        )
        if has_blocking and task.status == TaskIntelligenceStatus.READY:
            task.status = TaskIntelligenceStatus.NEEDS_CLARIFICATION

        return task

    async def analyze(self, raw_request: str) -> EngineeringTask:
        """
        Analyze a raw user request and generate a structured EngineeringTask.

        Args:
            raw_request: The raw user request.

        Returns:
            A validated EngineeringTask.

        Raises:
            TaskIntelligenceParseError: If the model output is malformed or invalid.
            LLMError: If the underlying model provider fails.
        """
        schema = EngineeringTask.model_json_schema()

        system_prompt = (
            "You are a Task Intelligence Agent.\n"
            "Your objective is to read a raw user request and produce a structured engineering task.\n\n"
            "CRITICAL RULES:\n"
            "1. DISTINGUISH FACTS FROM ASSUMPTIONS: Do not treat inferred details as requirements.\n"
            "2. EXPLICIT CONSTRAINTS: Only list constraints if clearly implied or stated.\n"
            "3. AMBIGUITY DETECTION: If the request lacks critical details needed for implementation, "
            "list them in ambiguities. Use BLOCKING severity if implementation cannot safely begin without clarification.\n"
            "4. NO IMPLEMENTATION DETAILS: Do not invent technical architecture; focus on the 'what', not the 'how'.\n"
            "5. STATUS: Set status to NEEDS_CLARIFICATION if there are BLOCKING ambiguities. Otherwise, READY.\n"
            "Respond ONLY with a valid JSON object matching this schema:\n"
            f"{json.dumps(schema)}"
        )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=raw_request),
        ]

        request = LLMRequest(
            messages=messages,
            temperature=0.1,
            model="task-intelligence-model"
        )

        response = await self.llm.generate(request)

        try:
            content = response.content or ""
            # Strip potential markdown formatting
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]

            task = EngineeringTask.model_validate_json(content.strip())

            # Ensure task_id exists
            if not task.task_id:
                task.task_id = str(uuid.uuid4())

            # Always preserve the exact original request
            task.original_request = raw_request

            return self._validate_application_rules(task)
        except ValidationError as e:
            raise TaskIntelligenceParseError(f"Failed to parse EngineeringTask: {e}") from e
