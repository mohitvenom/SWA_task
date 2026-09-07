"""Domain errors for the Git workspace subsystem."""


class GitError(Exception):
    """Base exception for all Git-related errors."""


class GitUnavailableError(GitError):
    """Raised when the Git executable is not found."""


class GitRepositoryNotFoundError(GitError):
    """Raised when a workspace is not a valid Git repository."""


class GitWorkspaceError(GitError):
    """Raised when the workspace path itself is invalid (missing, not directory)."""


class GitDirtyWorkspaceError(GitError):
    """Raised when an operation requires a clean working tree but it is dirty."""


class GitInvalidBranchError(GitError):
    """Raised when a branch name contains invalid characters."""


class GitBranchExistsError(GitError):
    """Raised when attempting to create a branch that already exists."""


class GitCheckoutError(GitError):
    """Raised when a checkout operation fails (e.g., conflicts)."""


class GitStageError(GitError):
    """Raised when staging files fails (e.g., absolute paths, sensitive files)."""


class GitCommitError(GitError):
    """Raised when a commit operation fails."""


class GitDiffError(GitError):
    """Raised when generating a diff fails."""


class GitRollbackError(GitError):
    """Raised when a rollback operation fails."""
