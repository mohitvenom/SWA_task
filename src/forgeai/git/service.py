import re
from pathlib import Path

from forgeai.config.settings import settings
from forgeai.execution.runner import ProcessRunner
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
    WorkspaceCheckpoint,
)


class GitCLIWorkspaceService(GitService):
    """GitService implementation using controlled subprocesses.

    This implementation explicitly prevents raw command execution or
    arbitrary path injection from LLM outputs.
    """

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self._max_diff_bytes = settings.git_max_diff_bytes
        self._sensitive_patterns = [
            r"^\.env.*",
            r"^.*\.pem$",
            r"^.*\.key$",
            r"^.*_rsa$",
        ]

        if not self.workspace_root.exists():
            raise GitWorkspaceError(f"Workspace does not exist: {self.workspace_root}")
        if not self.workspace_root.is_dir():
            raise GitWorkspaceError(
                f"Workspace is not a directory: {self.workspace_root}"
            )

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        """Execute a git command safely in the workspace.

        Uses ProcessRunner to safely invoke the command while handling timeouts,
        cancellation, and bounded output reliably across different async runtimes.
        """
        try:
            command = ["git"]
            command.extend(args)
            result = await ProcessRunner.run(
                command=command,
                cwd=str(self.workspace_root),
            )
            return (
                result.exit_code or 0,
                result.stdout.decode(errors="replace"),
                result.stderr.decode(errors="replace"),
            )
        except FileNotFoundError:
            raise GitUnavailableError("Git executable not found on system PATH.")
        except Exception as e:
            raise GitError(f"Failed to execute git subprocess: {e}")

    async def _check_is_repo(self) -> None:
        """Verify the workspace is a valid git repository."""
        code, _, stderr = await self._run_git("rev-parse", "--is-inside-work-tree")
        if code != 0:
            raise GitRepositoryNotFoundError("Workspace is not a Git repository.")

    def _parse_status_line(self, line: str) -> GitChange | None:
        """Parse a porcelain v1 status line."""
        if len(line) < 4:
            return None

        xy = line[0:2]
        path = line[3:].strip()

        # Determine change type and staged state
        staged = False
        change_type = ChangeType.UNKNOWN

        if xy == "??":
            change_type = ChangeType.UNTRACKED
        else:
            x, y = xy[0], xy[1]
            if x != " " and x != "?":
                staged = True

            # Map code to type (simplified)
            active_code = x if staged else y
            if active_code == "A":
                change_type = ChangeType.ADDED
            elif active_code == "M":
                change_type = ChangeType.MODIFIED
            elif active_code == "D":
                change_type = ChangeType.DELETED
            elif active_code == "R":
                change_type = ChangeType.RENAMED

        return GitChange(path=path, change_type=change_type, staged=staged)

    async def inspect_repository(self) -> GitStatus:
        await self._check_is_repo()

        code, stdout, stderr = await self._run_git(
            "status", "--porcelain=v1", "--branch"
        )
        if code != 0:
            raise GitError(f"Failed to get status: {stderr}")

        lines = stdout.splitlines()
        branch = "unknown"
        staged_changes = []
        unstaged_changes = []
        untracked_changes = []

        for line in lines:
            if line.startswith("## "):
                branch_info = line[3:].split("...")[0]
                branch = branch_info.split(" ")[0]
            else:
                change = self._parse_status_line(line)
                if change:
                    if change.change_type == ChangeType.UNTRACKED:
                        untracked_changes.append(change)
                    elif change.staged:
                        staged_changes.append(change)
                    else:
                        unstaged_changes.append(change)

        is_clean = (
            len(staged_changes) == 0
            and len(unstaged_changes) == 0
            and len(untracked_changes) == 0
        )

        return GitStatus(
            branch=branch,
            is_clean=is_clean,
            staged_changes=staged_changes,
            unstaged_changes=unstaged_changes,
            untracked_changes=untracked_changes,
        )

    async def get_status(self) -> GitStatus:
        return await self.inspect_repository()

    def _sanitize_branch_name(self, task_id: str) -> str:
        """Sanitize a task ID to create a valid Git branch name."""
        clean = re.sub(r"[^\w\-]", "_", task_id)
        if not clean:
            raise GitInvalidBranchError("Sanitized branch name is empty.")
        return f"forgeai/task/{clean}"

    async def create_branch(self, task_id: str) -> GitBranch:
        await self._check_is_repo()
        status = await self.get_status()
        if not status.is_clean:
            raise GitDirtyWorkspaceError("Cannot create branch: working tree is dirty.")

        branch_name = self._sanitize_branch_name(task_id)

        # Check if branch exists
        code, _, _ = await self._run_git(
            "show-ref", "--verify", f"refs/heads/{branch_name}"
        )
        if code == 0:
            raise GitBranchExistsError(f"Branch already exists: {branch_name}")

        code, _, stderr = await self._run_git("checkout", "-b", branch_name)
        if code != 0:
            raise GitError(f"Failed to create branch: {stderr}")

        return GitBranch(name=branch_name, is_current=True, is_remote=False)

    async def checkout_branch(self, name: str) -> None:
        await self._check_is_repo()

        # Don't allow flags or malformed branch names
        if name.startswith("-") or " " in name:
            raise GitInvalidBranchError(f"Invalid branch name: {name}")

        code, _, stderr = await self._run_git("checkout", name)
        if code != 0:
            raise GitCheckoutError(f"Checkout failed: {stderr}")

    async def get_diff(self) -> GitDiff:
        """Get the diff for the current workspace, bounded by size limits.

        Note: Untracked files are not represented in the returned patch.
        """
        await self._check_is_repo()

        # Get diff of tracked files
        code, patch, stderr = await self._run_git("diff", "HEAD")
        if code != 0:
            raise GitDiffError(f"Failed to get diff: {stderr}")

        # Get diff stats
        code, stat_out, _ = await self._run_git("diff", "HEAD", "--shortstat")

        changed_files = 0
        insertions = 0
        deletions = 0

        if stat_out.strip():
            # Example: " 2 files changed, 5 insertions(+), 1 deletion(-)"
            match_files = re.search(r"(\d+) file", stat_out)
            match_ins = re.search(r"(\d+) insertion", stat_out)
            match_del = re.search(r"(\d+) deletion", stat_out)

            if match_files:
                changed_files = int(match_files.group(1))
            if match_ins:
                insertions = int(match_ins.group(1))
            if match_del:
                deletions = int(match_del.group(1))

        patch_bytes = patch.encode("utf-8", errors="replace")
        truncated = False
        if len(patch_bytes) > self._max_diff_bytes:
            patch = (
                patch_bytes[: self._max_diff_bytes].decode("utf-8", errors="replace")
                + "\n...[TRUNCATED]..."
            )
            truncated = True

        return GitDiff(
            changed_files=changed_files,
            insertions=insertions,
            deletions=deletions,
            patch=patch,
            truncated=truncated,
        )

    def _validate_path(self, path: str) -> None:
        """Validate path is relative and safe."""
        if Path(path).is_absolute():
            raise GitStageError(f"Absolute paths are forbidden: {path}")
        if ".." in Path(path).parts:
            raise GitStageError(f"Path traversal is forbidden: {path}")

        file_name = Path(path).name
        for pattern in self._sensitive_patterns:
            if re.match(pattern, file_name):
                raise GitStageError(f"Staging sensitive files is forbidden: {path}")

    async def stage_files(self, paths: list[str]) -> None:
        await self._check_is_repo()
        if not paths:
            return

        for p in paths:
            if p == "." or p == "-A":
                raise GitStageError("Implicit full-repository staging is forbidden.")
            self._validate_path(p)

        code, _, stderr = await self._run_git("add", "--", *paths)
        if code != 0:
            raise GitStageError(f"Failed to stage files: {stderr}")

    async def commit(self, message: str, paths: list[str]) -> GitCommit:
        await self._check_is_repo()
        if not message.strip():
            raise GitCommitError("Commit message cannot be empty.")
        if not paths:
            raise GitCommitError("Paths must be explicitly provided for commit.")

        # ISSUE 1: Invariant - NO COMMITTED FILE MAY EXIST OUTSIDE THE EXPLICITLY
        # REQUESTED PATH SET
        # Equivalently: COMMITTED FILES <= EXPLICITLY REQUESTED FILES
        status_before = await self.get_status()
        pre_staged_paths = {change.path for change in status_before.staged_changes}
        requested_paths_set = set(paths)

        # If there are already staged files that aren't in the requested paths, reject.
        # This prevents accidental commits of unrelated files.
        unrelated_staged = pre_staged_paths - requested_paths_set
        if unrelated_staged:
            raise GitCommitError(
                "Refusing to commit: there are staged changes outside the explicitly "
                f"requested paths: {unrelated_staged}"
            )

        await self.stage_files(paths)

        status_after = await self.get_status()
        post_staged_paths = {change.path for change in status_after.staged_changes}

        # Verify exactly the requested paths are staged
        # Note: If a requested path has no changes, it won't be in post_staged_paths,
        # but the invariant is that we ONLY commit requested paths. If there are extra
        # paths staged, we fail.
        unexpected_staged = post_staged_paths - requested_paths_set
        if unexpected_staged:
            raise GitCommitError(
                "Refusing to commit: invariant check failed, unexpected files are "
                f"staged: {unexpected_staged}"
            )

        if not post_staged_paths:
            raise GitCommitError("No changes to commit for the requested paths.")

        code, _, stderr = await self._run_git("commit", "-m", message)
        if code != 0:
            raise GitCommitError(f"Commit failed: {stderr}")

        # Get the new commit hash
        code, hash_out, _ = await self._run_git("rev-parse", "HEAD")
        commit_hash = hash_out.strip()

        # Get current branch
        status = await self.get_status()

        return GitCommit(commit_hash=commit_hash, message=message, branch=status.branch)

    async def create_checkpoint(self, task_id: str) -> WorkspaceCheckpoint:
        status = await self.get_status()
        if not status.is_clean:
            raise GitDirtyWorkspaceError(
                "Cannot create checkpoint: workspace must be completely clean "
                "(no staged, unstaged, or untracked files)."
            )

        code, hash_out, _ = await self._run_git("rev-parse", "HEAD")
        commit_hash = hash_out.strip() if code == 0 else ""

        return WorkspaceCheckpoint(
            task_id=task_id,
            branch=status.branch,
            commit_hash=commit_hash,
            status=status,
        )

    async def rollback_files(self, paths: list[str]) -> None:
        await self._check_is_repo()
        if not paths:
            return

        for p in paths:
            self._validate_path(p)

        # Restore tracked files to HEAD. Note: this does not affect untracked files.
        code, _, stderr = await self._run_git("checkout", "HEAD", "--", *paths)
        if code != 0:
            raise GitRollbackError(f"Failed to rollback files: {stderr}")

    async def restore_checkpoint(self, checkpoint: WorkspaceCheckpoint) -> None:
        await self._check_is_repo()

        if not checkpoint.commit_hash:
            raise GitRollbackError("Checkpoint commit hash is empty.")

        # VALIDATION PHASE
        # Verify commit exists and is a commit
        code, out, _ = await self._run_git("cat-file", "-t", checkpoint.commit_hash)
        if code != 0 or out.strip() != "commit":
            raise GitRollbackError(
                "Refusing to restore: Invalid checkpoint commit hash "
                f"'{checkpoint.commit_hash}'."
            )

        # Verify branch exists locally
        code, _, _ = await self._run_git(
            "show-ref", "--verify", f"refs/heads/{checkpoint.branch}"
        )
        if code != 0:
            raise GitRollbackError(
                f"Refusing to restore: Invalid checkpoint branch '{checkpoint.branch}'."
            )

        # Verify checkpoint commit is reachable from the branch
        code, _, _ = await self._run_git(
            "merge-base",
            "--is-ancestor",
            checkpoint.commit_hash,
            f"refs/heads/{checkpoint.branch}",
        )
        if code != 0:
            raise GitRollbackError(
                f"Refusing to restore: Checkpoint commit '{checkpoint.commit_hash}' "
                f"is not reachable from branch '{checkpoint.branch}'."
            )

        # PRECONDITION PHASE
        # Enforce safe precondition: do not destroy uncommitted tracked changes
        status = await self.get_status()
        if status.staged_changes or status.unstaged_changes:
            raise GitRollbackError(
                "Refusing to restore checkpoint: there are uncommitted tracked changes "
                "that would be destroyed."
            )

        # Untracked File Conflict Detection
        if status.untracked_changes:
            # List all files in the target commit tree
            code, tree_out, _ = await self._run_git(
                "ls-tree", "-r", "--name-only", checkpoint.commit_hash
            )
            if code == 0:
                tree_files = tree_out.splitlines()
                for change in status.untracked_changes:
                    untracked_path = Path(change.path)
                    for tree_file in tree_files:
                        t_path = Path(tree_file)
                        # Detect exact path conflicts and ancestor/descendant
                        # directory conflicts
                        if (
                            t_path == untracked_path
                            or t_path.is_relative_to(untracked_path)
                            or untracked_path.is_relative_to(t_path)
                        ):
                            raise GitRollbackError(
                                "Refusing to restore checkpoint: untracked path "
                                f"'{change.path}' conflicts with the target "
                                "checkpoint tree and would be overwritten."
                            )

        # EXECUTION PHASE
        # Safely switch to the branch
        await self.checkout_branch(checkpoint.branch)

        # Only hard reset tracked files to the specific commit.
        # This intentionally does NOT run `git clean -fd` to preserve non-conflicting
        # untracked user data.
        code, _, stderr = await self._run_git("reset", "--hard", checkpoint.commit_hash)
        if code != 0:
            raise GitRollbackError(f"Failed to restore checkpoint commit: {stderr}")
