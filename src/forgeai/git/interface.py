"""Interface definitions for the Git subsystem."""

from typing import Protocol

from forgeai.git.models import (
    GitBranch,
    GitCommit,
    GitDiff,
    GitStatus,
    WorkspaceCheckpoint,
)


class GitService(Protocol):
    """Provider-independent interface for Git workspace operations.

    This protocol explicitly blocks raw command execution and focuses only on
    typed domain operations required by future agents.
    """

    async def inspect_repository(self) -> GitStatus:
        """Inspect the repository and return its current status."""
        ...

    async def get_status(self) -> GitStatus:
        """Get the current repository status (alias for inspect_repository)."""
        ...

    async def create_branch(self, task_id: str) -> GitBranch:
        """Create a new task branch safely. Fails if tree is dirty."""
        ...

    async def checkout_branch(self, name: str) -> None:
        """Checkout an existing branch safely."""
        ...

    async def get_diff(self) -> GitDiff:
        """Get the diff for the current workspace, bounded by size limits."""
        ...

    async def stage_files(self, paths: list[str]) -> None:
        """Stage explicitly supplied tracked or untracked paths safely."""
        ...

    async def commit(self, message: str, paths: list[str]) -> GitCommit:
        """Commit explicitly requested paths.

        Guarantees that no committed file exists outside the explicitly
        requested path set (COMMITTED FILES <= EXPLICITLY REQUESTED FILES).
        """
        ...

    async def create_checkpoint(self, task_id: str) -> WorkspaceCheckpoint:
        """Create a logical point in time for a rollback.

        Requires the workspace to be completely clean.
        """
        ...

    async def rollback_files(self, paths: list[str]) -> None:
        """Restore specific tracked files to HEAD. Untracked files are untouched."""
        ...

    async def restore_checkpoint(self, checkpoint: WorkspaceCheckpoint) -> None:
        """Restore the workspace safely back to the checkpoint's commit."""
        ...
