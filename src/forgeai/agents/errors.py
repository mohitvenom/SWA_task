"""Domain errors for agent orchestration."""


class AgentError(Exception):
    """Base exception for all agent orchestration errors."""

    pass


class AgentStateTransitionError(AgentError):
    """Raised when an invalid state transition is attempted."""

    pass


class AgentMaxIterationsError(AgentError):
    """Raised when the maximum number of allowed agent iterations is exceeded."""

    pass


class AgentDecisionParseError(AgentError):
    """Raised when the LLM returns an unparseable or invalid decision structure."""

    pass


class PlanningError(AgentError):
    """Raised when the planning agent fails to generate a valid plan."""

    pass


class PlanValidationError(PlanningError):
    """Raised when the LLM generates an invalid or malformed plan structure."""

    pass


class TaskIntelligenceError(AgentError):
    """Base exception for task intelligence failures."""

    pass


class TaskIntelligenceParseError(TaskIntelligenceError):
    """Raised when the LLM generates an invalid or malformed task intelligence output."""

    pass


class TestStrategyError(AgentError):
    """Base exception for test strategy failures."""

    pass


class TestStrategyParseError(TestStrategyError):
    """Raised when the LLM generates an invalid or malformed test strategy output."""

    pass


class TestStrategyValidationError(TestStrategyError):
    """Raised when the test strategy fails deterministic application validation."""

    pass


class FailureDiagnosisError(AgentError):
    """Base exception for failure diagnosis failures."""

    pass


class FailureDiagnosisParseError(FailureDiagnosisError):
    """Raised when the LLM generates an invalid or malformed diagnosis structure."""

    pass


class FailureDiagnosisValidationError(FailureDiagnosisError):
    """Raised when the diagnosis or repair plan fails application-level validation."""

    pass


class RepairPlanValidationError(FailureDiagnosisError):
    """Raised when the repair plan violates authorization, bounds, or sandbox limits."""

    pass


class EnvironmentIntelligenceError(AgentError):
    """Base exception for environment intelligence failures."""

    pass


class DependencyParseError(EnvironmentIntelligenceError):
    """Raised when a dependency file (pyproject.toml, requirements.txt, etc.) cannot be parsed."""

    pass


class EnvironmentSnapshotError(EnvironmentIntelligenceError):
    """Raised when the environment snapshot cannot be collected."""

    pass


class EnvironmentDiagnosisError(EnvironmentIntelligenceError):
    """Raised when environment diagnosis fails (e.g., malformed LLM output)."""

    pass
