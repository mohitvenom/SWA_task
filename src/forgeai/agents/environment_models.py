"""Domain models for Dependency & Environment Intelligence (Phase 16)."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DependencySource(str, Enum):
    """The file/format from which a dependency declaration was read."""

    PYPROJECT = "PYPROJECT"
    REQUIREMENTS = "REQUIREMENTS"
    LOCKFILE = "LOCKFILE"
    SETUP_PY = "SETUP_PY"
    SETUP_CFG = "SETUP_CFG"
    PIPFILE = "PIPFILE"
    OTHER = "OTHER"


class LockfileType(str, Enum):
    """The type of lockfile detected."""

    POETRY_LOCK = "POETRY_LOCK"
    UV_LOCK = "UV_LOCK"
    PIPFILE_LOCK = "PIPFILE_LOCK"
    PDM_LOCK = "PDM_LOCK"
    UNKNOWN = "UNKNOWN"


class DependencyState(str, Enum):
    """
    The reconciled state of a dependency across declared/installed/locked views.

    DECLARED_ONLY        – declared in a config file; install status unknown.
    INSTALLED_ONLY       – present in the environment; not declared in any config.
    DECLARED_AND_INSTALLED – declared and detected as installed.
    DECLARED_BUT_NOT_INSTALLED – declared but NOT found in the environment.
    VERSION_MISMATCH     – declared and installed, but version constraint violated.
    LOCKED               – version pinned in a lockfile (install status not checked).
    UNKNOWN              – state cannot be determined.
    """

    DECLARED_ONLY = "DECLARED_ONLY"
    INSTALLED_ONLY = "INSTALLED_ONLY"
    DECLARED_AND_INSTALLED = "DECLARED_AND_INSTALLED"
    DECLARED_BUT_NOT_INSTALLED = "DECLARED_BUT_NOT_INSTALLED"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    LOCKED = "LOCKED"
    UNKNOWN = "UNKNOWN"


class EnvironmentDiagnosisCategory(str, Enum):
    """Categorisation of the environment-level problem detected."""

    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    PYTHON_VERSION_MISMATCH = "PYTHON_VERSION_MISMATCH"
    ENVIRONMENT_INCOMPLETE = "ENVIRONMENT_INCOMPLETE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    NO_ISSUE_DETECTED = "NO_ISSUE_DETECTED"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class VersionConstraint(BaseModel):
    """A single parsed version constraint (e.g. >=2.0, ~=1.4)."""

    raw_spec: str
    """The original specifier string exactly as found in the source file."""

    operator: str | None = None
    """Comparison operator (>=, ==, ~=, !=, <, <=)."""

    version: str | None = None
    """Version string after the operator."""

    is_parseable: bool = True
    """False when the specifier cannot be safely interpreted."""


class DeclaredDependency(BaseModel):
    """A dependency as declared in a project configuration file."""

    name: str
    """Normalised package name (lowercase, hyphens replaced with underscores)."""

    version_constraints: list[VersionConstraint] = Field(default_factory=list)
    """Parsed version specifiers; empty means unconstrained."""

    source: DependencySource
    """Which file/format this declaration came from."""

    source_file: str
    """Relative path to the file that contains this declaration."""

    optional_group: str | None = None
    """
    For pyproject optional-dependencies or dependency groups, the group name.
    None for core/mandatory dependencies.
    """

    is_dev: bool = False
    """True for development/test-only dependencies."""

    raw_line: str = ""
    """The original line from the source file, for traceability."""

    is_parseable: bool = True
    """False when this line could not be safely parsed."""


class InstalledPackage(BaseModel):
    """A package detected in the current Python environment."""

    name: str
    """Normalised package name."""

    version: str
    """Installed version string."""


class LockfileInfo(BaseModel):
    """Metadata about a detected lockfile."""

    path: str
    """Relative path to the lockfile."""

    lockfile_type: LockfileType
    """The type of lockfile detected."""

    is_parseable: bool = False
    """
    True only if Phase 16 can safely extract locked versions from this format.
    Currently, detection-only; parsing is limited.
    """

    locked_package_count: int | None = None
    """Number of locked packages, if deterministically extractable."""


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


class DependencySnapshot(BaseModel):
    """
    Immutable structured snapshot of all dependency information discovered
    in a repository. Distinguishes DECLARED, INSTALLED, and LOCKED states.
    """

    declared: list[DeclaredDependency] = Field(default_factory=list)
    """All dependency declarations found across all source files."""

    installed: list[InstalledPackage] = Field(default_factory=list)
    """
    Packages detected in the active Python environment via importlib.metadata.
    Limited to max 500 entries to bound context size.
    """

    lockfiles: list[LockfileInfo] = Field(default_factory=list)
    """Lockfiles detected in the repository root."""

    dependency_file_paths: list[str] = Field(default_factory=list)
    """All dependency-related files found (relative paths)."""

    python_requires: str | None = None
    """The requires-python specifier from pyproject.toml, if present."""

    collection_errors: dict[str, str] = Field(default_factory=dict)
    """
    Mapping of source file → error message for any file that could not be
    fully parsed. Presence means partial data; not a fatal error.
    """


class EnvironmentSnapshot(BaseModel):
    """
    Immutable structured snapshot of the Python runtime environment.

    SECURITY: This model MUST NOT contain secret values, credentials,
    API keys, or arbitrary environment variable values.
    """

    python_version: str
    """Full Python version string, e.g. '3.12.3'."""

    python_version_info: list[int] = Field(default_factory=list)
    """[major, minor, micro] as integers."""

    python_executable: str
    """Absolute path to the Python interpreter."""

    platform: str
    """Operating system platform identifier."""

    is_venv: bool = False
    """True when a virtual environment is active."""

    virtual_env_path: str | None = None
    """Path to the active virtual environment, if any."""

    collection_errors: list[str] = Field(default_factory=list)
    """Non-fatal errors encountered during environment snapshot collection."""


# ---------------------------------------------------------------------------
# Analysis and diagnosis
# ---------------------------------------------------------------------------


class DependencyCheckResult(BaseModel):
    """The reconciled state of a single declared dependency."""

    name: str
    state: DependencyState
    declared_version_spec: str | None = None
    """The raw version specifier string as declared."""
    installed_version: str | None = None
    """The installed version, if found."""
    is_compatible: bool | None = None
    """
    True/False when compatibility is deterministically established;
    None when compatibility cannot be determined.
    """


class EnvironmentFact(BaseModel):
    """
    A single piece of evidence about the environment.

    is_deterministic distinguishes facts obtained without inference from
    LLM-generated inferences. Facts MUST be grounded in deterministic
    discovery (filesystem, sys, importlib.metadata).
    """

    description: str
    is_deterministic: bool
    """True = obtained via deterministic means; False = LLM inference."""
    source: str
    """Where this fact came from (e.g., 'pyproject.toml', 'sys.version', 'LLM')."""


class EnvironmentDiagnosis(BaseModel):
    """
    The structured output of Environment Intelligence analysis.

    IMPORTANT: This is NOT an authorization to install packages or mutate
    files. It is purely a structured evidence report.
    """

    category: EnvironmentDiagnosisCategory
    summary: str
    facts: list[EnvironmentFact] = Field(default_factory=list)
    """Deterministically established facts (is_deterministic=True)."""
    inferences: list[EnvironmentFact] = Field(default_factory=list)
    """LLM-derived interpretations (is_deterministic=False)."""
    dependency_issues: list[DependencyCheckResult] = Field(default_factory=list)
    """Specific per-package reconciliation results."""
    python_version_compatible: bool | None = None
    """None = unknown; True/False = deterministically established."""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    recommended_action: str = ""
    """
    Human-readable recommendation. NOT an execution command.
    Phase 16 does NOT act on this.
    """
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
