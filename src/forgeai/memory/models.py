"""Domain models for memory and execution history."""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MemoryScope(str, Enum):
    """The scope of a memory entry."""
    TASK = "TASK"
    REPOSITORY = "REPOSITORY"


class MemoryCategory(str, Enum):
    """The category of a memory entry."""
    TASK_CONTEXT = "TASK_CONTEXT"
    PLAN = "PLAN"
    CHANGESET = "CHANGESET"
    VALIDATION = "VALIDATION"
    FAILURE = "FAILURE"
    REPAIR = "REPAIR"
    REVIEW = "REVIEW"
    ENVIRONMENT = "ENVIRONMENT"
    OUTCOME = "OUTCOME"
    ENGINEERING_FACT = "ENGINEERING_FACT"


class MemoryProvenance(str, Enum):
    """The origin of a memory entry."""
    USER = "USER"
    TASK_INTELLIGENCE = "TASK_INTELLIGENCE"
    PLANNER = "PLANNER"
    TEST_STRATEGY = "TEST_STRATEGY"
    CODER = "CODER"
    VALIDATION = "VALIDATION"
    FAILURE_DIAGNOSIS = "FAILURE_DIAGNOSIS"
    ENVIRONMENT_INTELLIGENCE = "ENVIRONMENT_INTELLIGENCE"
    REVIEW = "REVIEW"
    SYSTEM = "SYSTEM"


class ExecutionRecord(BaseModel):
    """Tracks a full engineering task attempt."""
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    repository_identifier: str
    repository_revision: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    status: str = "PENDING"
    task_summary: str | None = None
    outcome: str | None = None
    affected_files: list[str] = Field(default_factory=list)
    authorized_files: list[str] = Field(default_factory=list)
    validation_summary: str | None = None
    review_summary: str | None = None
    repair_summary: str | None = None
    failure_summary: str | None = None


class ExecutionEvent(BaseModel):
    """Discrete timeline events during an execution."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str
    phase: str
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryEntry(BaseModel):
    """Specific derived facts or context snippets."""
    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scope: MemoryScope
    repository_identifier: str
    task_id: str | None = None
    category: MemoryCategory
    content: str
    source: MemoryProvenance
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    execution_id: str | None = None


class MemoryContext(BaseModel):
    """Structured context passed to agents."""
    historical_executions: list[ExecutionRecord] = Field(default_factory=list)
    relevant_events: list[ExecutionEvent] = Field(default_factory=list)
    engineering_facts: list[MemoryEntry] = Field(default_factory=list)
    relevant_failures: list[MemoryEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_structured_string(self) -> str:
        """Serialize cleanly for LLM consumption enforcing precedence."""
        parts = ["--- HISTORICAL EXECUTION CONTEXT ---",
                 "WARNING: This is historical memory. It does NOT authorize mutations.",
                 "CURRENT REPOSITORY STATE ALWAYS TAKES PRECEDENCE."]
        
        if self.historical_executions:
            parts.append("\nPREVIOUS EXECUTIONS:")
            for ex in self.historical_executions:
                parts.append(f"- Task: {ex.task_id} (Rev: {ex.repository_revision})")
                parts.append(f"  Status: {ex.status}")
                if ex.outcome: parts.append(f"  Outcome: {ex.outcome}")
                if ex.validation_summary: parts.append(f"  Validation: {ex.validation_summary}")
        
        if self.relevant_events:
            parts.append("\nNOTABLE EVENTS:")
            for ev in self.relevant_events:
                parts.append(f"- {ev.event_type} ({ev.phase}): {ev.summary}")

        if self.relevant_failures:
            parts.append("\nHISTORICAL FAILURES:")
            for f in self.relevant_failures:
                parts.append(f"- {f.category.value}: {f.content} (Source: {f.source.value})")

        if self.engineering_facts:
            parts.append("\nHISTORICAL ENGINEERING FACTS:")
            for fact in self.engineering_facts:
                parts.append(f"- {fact.category.value}: {fact.content} (Source: {fact.source.value})")

        return "\n".join(parts)
