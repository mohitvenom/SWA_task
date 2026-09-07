"""Domain models for repository intelligence."""

from pydantic import BaseModel, Field


class LanguageStats(BaseModel):
    """Statistics for a specific language in the repository."""

    file_count: int = 0
    total_bytes: int = 0


class RepositorySymbol(BaseModel):
    """A code symbol (class, function, etc.) extracted from the repository."""

    name: str
    symbol_type: str  # "class", "function", "async_function"
    file_path: str
    line_number: int | None = None


class RepositoryDependency(BaseModel):
    """A dependency or import found in the repository."""

    name: str
    file_path: str


class RepositoryEntryPoint(BaseModel):
    """A candidate entry point for the application."""

    file_path: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)


class RepositoryFile(BaseModel):
    """Metadata for a single file in the repository."""

    relative_path: str
    extension: str
    language: str
    size_bytes: int
    is_test: bool = False
    is_generated_or_vendor: bool = False


class RepositorySnapshot(BaseModel):
    """A deterministic snapshot of a repository's structure and contents."""

    repository_root: str
    total_files_found: int = 0
    total_analyzed_files: int = 0
    language_stats: dict[str, LanguageStats] = Field(default_factory=dict)
    files: list[RepositoryFile] = Field(default_factory=list)
    important_files: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    symbols: list[RepositorySymbol] = Field(default_factory=list)
    dependencies: list[RepositoryDependency] = Field(default_factory=list)
    entry_points: list[RepositoryEntryPoint] = Field(default_factory=list)
    analysis_errors: dict[str, str] = Field(default_factory=dict)
