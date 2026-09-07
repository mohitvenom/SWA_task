"""Git workspace management subsystem."""

from forgeai.git.errors import (
    GitBranchExistsError,
    GitCheckoutError,
    GitCommitError,
    GitDiffError,
    GitDirtyWorkspaceError,
    GitError,
    GitInvalidBranchError,
    GitRepositoryNotFoundError,
    GitRollbackError,
    GitStageError,
    GitUnavailableError,
    GitWorkspaceError,
)
from forgeai.git.interface import GitService
from forgeai.git.models import (
    ChangeType,
    GitBranch,
    GitChange,
    GitCommit,
    GitDiff,
    GitStatus,
    Workspace,
    WorkspaceCheckpoint,
)
from forgeai.git.service import GitCLIWorkspaceService

__all__ = [
    "ChangeType",
    "GitBranch",
    "GitBranchExistsError",
    "GitCLIWorkspaceService",
    "GitChange",
    "GitCheckoutError",
    "GitCommit",
    "GitCommitError",
    "GitDiff",
    "GitDiffError",
    "GitDirtyWorkspaceError",
    "GitError",
    "GitInvalidBranchError",
    "GitRepositoryNotFoundError",
    "GitRollbackError",
    "GitService",
    "GitStageError",
    "GitStatus",
    "GitUnavailableError",
    "GitWorkspaceError",
    "Workspace",
    "WorkspaceCheckpoint",
]
