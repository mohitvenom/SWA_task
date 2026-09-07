"""Domain models for agent orchestration."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
import uuid


class AgentState(str, Enum):
    """Enumeration of possible agent states."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    THINKING = "THINKING"
    TOOL_EXECUTING = "TOOL_EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentTask(BaseModel):
    """A high-level task for an agent to accomplish."""

    task_id: str
    description: str
    status: AgentState = AgentState.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskIntelligenceStatus(str, Enum):
    """Status of the task intelligence analysis."""

    READY = "READY"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    REJECTED = "REJECTED"


class AmbiguitySeverity(str, Enum):
    """Severity of a detected ambiguity."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKING = "BLOCKING"


class TaskRiskLevel(str, Enum):
    """Assessed risk level of a task."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TaskAmbiguity(BaseModel):
    """An ambiguity identified in the original request."""

    question: str
    severity: AmbiguitySeverity


class EngineeringTask(BaseModel):
    """A structured engineering task derived from a user request."""

    task_id: str | None = None
    original_request: str
    objective: str
    requirements: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[TaskAmbiguity] = Field(default_factory=list)
    risk_level: TaskRiskLevel = TaskRiskLevel.LOW
    validation_expectations: list[str] = Field(default_factory=list)
    status: TaskIntelligenceStatus = TaskIntelligenceStatus.READY


class AgentDecision(BaseModel):
    """Structured decision output from the LLM."""

    decision: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    next_state: AgentState
    data: dict[str, Any] = Field(default_factory=dict)


class AgentStep(BaseModel):
    """A record of a single orchestration step."""

    step_id: str
    sequence: int
    state: AgentState
    start_time: datetime
    end_time: datetime | None = None
    success: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentSession(BaseModel):
    """An execution session for a given task."""

    session_id: str
    task_id: str
    current_state: AgentState = AgentState.PENDING
    iteration_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    steps: list[AgentStep] = Field(default_factory=list)


class AgentResult(BaseModel):
    """The final result of an orchestration run."""

    success: bool
    final_state: AgentState
    session: AgentSession
    error_message: str | None = None


class PlanStep(BaseModel):
    """A single implementation step in an engineering plan."""

    step_number: int
    objective: str
    target_files: list[str] = Field(default_factory=list)
    change_description: str
    dependencies_on_steps: list[int] = Field(default_factory=list)
    validation_requirement: str


class FileRelationshipType(str, Enum):
    """Types of relationships between files."""

    IMPORTS = "IMPORTS"
    IMPORTED_BY = "IMPORTED_BY"
    DEFINES = "DEFINES"
    REFERENCES = "REFERENCES"
    TESTS = "TESTS"
    CONFIGURES = "CONFIGURES"
    IMPLEMENTS = "IMPLEMENTS"
    INTERFACE_FOR = "INTERFACE_FOR"
    DEPENDS_ON = "DEPENDS_ON"
    REPLACED_BY = "REPLACED_BY"
    MOVED_TO = "MOVED_TO"
    GENERATED_FROM = "GENERATED_FROM"


class FileRelationship(BaseModel):
    """A relationship between two files."""

    source_file: str
    target_file: str
    relationship_type: FileRelationshipType
    reason: str
    is_deterministic: bool = False
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class ChangeOperation(str, Enum):
    """Types of mutation operations."""

    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"


class FileChange(BaseModel):
    """A planned mutation to a specific file."""

    file_path: str
    operation: ChangeOperation
    rationale: str


class ScopeExpansionReason(str, Enum):
    """Reasons for expanding the authorized change scope."""

    DEPENDENCY_DISCOVERY = "DEPENDENCY_DISCOVERY"
    TEST_DISCOVERY = "TEST_DISCOVERY"
    EXPLICIT_REQUEST = "EXPLICIT_REQUEST"


class ScopeExpansionRequest(BaseModel):
    """A request to expand the authorized scope."""

    file_path: str
    reason: ScopeExpansionReason
    rationale: str
    source_evidence: str


class ScopeExpansionDecision(str, Enum):
    """The result of a scope expansion request."""

    APPROVED = "APPROVED"
    REJECTED_EXCLUDED = "REJECTED_EXCLUDED"
    REJECTED_SENSITIVE = "REJECTED_SENSITIVE"
    REJECTED_LIMIT_EXCEEDED = "REJECTED_LIMIT_EXCEEDED"
    REJECTED_OUT_OF_BOUNDS = "REJECTED_OUT_OF_BOUNDS"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"


class ScopeExpansionRecord(BaseModel):
    """An auditable record of a scope expansion decision."""

    request: ScopeExpansionRequest
    decision: ScopeExpansionDecision
    decision_reason: str


class ChangeSetStatus(str, Enum):
    """The authorization status of a ChangeSet."""

    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"


class ChangeSet(BaseModel):
    """A bounded, dependency-aware collection of coordinated repository changes."""

    change_set_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    objective: str
    initial_files: list[FileChange] = Field(default_factory=list)
    discovered_files: list[FileChange] = Field(default_factory=list)
    authorized_files: list[str] = Field(default_factory=list)
    created_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    relationships: list[FileRelationship] = Field(default_factory=list)
    expansion_history: list[ScopeExpansionRecord] = Field(default_factory=list)
    status: ChangeSetStatus = ChangeSetStatus.PROPOSED



class EngineeringPlan(BaseModel):
    """A structured plan for executing an engineering task."""

    plan_id: str
    task_description: str
    task_interpretation: str
    discovered_facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    proposed_changes: str
    affected_files: list[str] = Field(default_factory=list)
    excluded_files: list[str] = Field(default_factory=list)
    change_set: ChangeSet | None = None
    steps: list[PlanStep] = Field(default_factory=list)
    dependencies_to_add: list[str] = Field(default_factory=list)
    tests_to_add_or_update: list[str] = Field(default_factory=list)
    validation_strategy: str
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class CodingPhase(str, Enum):
    """Enumeration of possible coding phases."""

    INITIALIZING = "INITIALIZING"
    INSPECTING = "INSPECTING"
    IMPLEMENTING = "IMPLEMENTING"
    VALIDATING = "VALIDATING"
    REPAIRING = "REPAIRING"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class CodingDecision(BaseModel):
    """Structured decision output from the LLM during coding."""

    action: str
    rationale_summary: str
    target_files: list[str] = Field(default_factory=list)
    completion_requested: bool = False


class CodingSession(BaseModel):
    """An execution session specific to the Coding Agent."""

    session_id: str
    task_id: str
    plan_id: str
    current_phase: CodingPhase = CodingPhase.INITIALIZING
    iteration_count: int = 0
    tool_call_count: int = 0
    repair_count: int = 0
    review_count: int = 0
    changed_files_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    branch: str | None = None
    checkpoint_hash: str | None = None


class ReviewSeverity(str, Enum):
    """Severity of a review finding."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReviewStatus(str, Enum):
    """The final status of a code review."""

    APPROVED = "APPROVED"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    REJECTED = "REJECTED"


class ReviewFinding(BaseModel):
    """A specific finding from the code review."""

    severity: ReviewSeverity
    category: str
    file: str | None = None
    description: str
    evidence: str
    recommendation: str


class ReviewDecision(BaseModel):
    """Structured decision output from the LLM reviewer."""

    status: ReviewStatus
    rationale_summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)


class ReviewResult(BaseModel):
    """The final evaluated result of a review cycle."""

    status: ReviewStatus
    findings: list[ReviewFinding] = Field(default_factory=list)
    reviewed_files: list[str] = Field(default_factory=list)
    iteration_count: int = 0
    plan_compliance: bool
    validation_summary: str | None = None
    error_message: str | None = None


class CodingResult(BaseModel):
    """The final result of a Coding Agent execution."""

    task_id: str
    success: bool
    final_phase: CodingPhase
    session: CodingSession
    changed_files: list[str] = Field(default_factory=list)
    validation_results: list[dict[str, Any]] = Field(default_factory=list)
    committed: bool = False
    commit_hash: str | None = None
    review_result: ReviewResult | None = None
    error_message: str | None = None
    summary: str


class TestType(str, Enum):
    """Categories of automated tests."""

    UNIT = "UNIT"
    INTEGRATION = "INTEGRATION"
    REGRESSION = "REGRESSION"
    END_TO_END = "END_TO_END"
    NEGATIVE = "NEGATIVE"
    EDGE_CASE = "EDGE_CASE"


class TestPriority(str, Enum):
    """Priority levels for testing validation."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TestCase(BaseModel):
    """A structured specification for a required test case."""

    name: str
    objective: str
    scenario: str
    expected_behavior: str
    priority: TestPriority
    test_type: TestType


class TestStrategyStatus(str, Enum):
    """Status of the test strategy generation."""

    READY = "READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class TestStrategy(BaseModel):
    """The validation and testing strategy derived for an engineering task."""

    task_id: str | None = None
    validation_goals: list[str] = Field(default_factory=list)
    relevant_existing_tests: list[str] = Field(default_factory=list)
    proposed_tests: list[str] = Field(default_factory=list)
    test_cases: list[TestCase] = Field(default_factory=list)
    edge_cases: list[str] = Field(default_factory=list)
    regression_targets: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    coverage_expectations: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    risk_considerations: list[str] = Field(default_factory=list)
    status: TestStrategyStatus = TestStrategyStatus.READY


class FailureCategory(str, Enum):
    """Broad categorization of validation failures."""

    TEST_FAILURE = "TEST_FAILURE"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    LINT_FAILURE = "LINT_FAILURE"
    IMPORT_ERROR = "IMPORT_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    TIMEOUT = "TIMEOUT"
    COMMAND_FAILURE = "COMMAND_FAILURE"
    UNKNOWN = "UNKNOWN"


class FailureSeverity(str, Enum):
    """Severity of the validation failure."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RepairAction(BaseModel):
    """A specific authorized repair action to be executed."""

    target_file: str
    rationale: str
    expected_effect: str


class RepairPlan(BaseModel):
    """A structured plan describing how to address a validation failure."""

    objective: str
    root_cause_addressed: str
    proposed_actions: list[RepairAction] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    risk: FailureSeverity


class DiagnosisStatus(str, Enum):
    """The status of the failure diagnosis process."""

    DIAGNOSED = "DIAGNOSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    UNRECOVERABLE = "UNRECOVERABLE"


class FailureDiagnosis(BaseModel):
    """The complete structured diagnosis of a validation failure."""

    failure_id: str
    category: FailureCategory
    severity: FailureSeverity
    symptom_summary: str
    root_cause_analysis: str
    confidence: float
    repair_plan: RepairPlan | None = None
    status: DiagnosisStatus = DiagnosisStatus.DIAGNOSED
