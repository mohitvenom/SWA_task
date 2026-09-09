"""Unit tests for the Git workspace management service."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from forgeai.execution.runner import ProcessResult

from forgeai.git.errors import (
    GitBranchExistsError,
    GitCommitError,
    GitDirtyWorkspaceError,
    GitInvalidBranchError,
    GitRepositoryNotFoundError,
    GitStageError,
    GitUnavailableError,
    GitWorkspaceError,
)
from forgeai.git.models import ChangeType
from forgeai.git.service import GitCLIWorkspaceService


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def git_service(workspace_dir: Path) -> GitCLIWorkspaceService:
    return GitCLIWorkspaceService(workspace_dir)


class MockGitService(GitCLIWorkspaceService):
    def __init__(self, workspace_root: Path):
        super().__init__(workspace_root)
        self.mock_run_git = AsyncMock(return_value=(0, "", ""))

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        return await self.mock_run_git(*args)


# ==============================================================================
# Initialization & Path Checks
# ==============================================================================


def test_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(GitWorkspaceError, match="Workspace does not exist"):
        GitCLIWorkspaceService(tmp_path / "missing")


def test_not_directory_workspace(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.touch()
    with pytest.raises(GitWorkspaceError, match="Workspace is not a directory"):
        GitCLIWorkspaceService(f)


# ==============================================================================
# Subprocess / Low-Level
# ==============================================================================


@pytest.mark.anyio
@patch("forgeai.git.service.ProcessRunner.run")
async def test_run_git_success(
    mock_run: AsyncMock, git_service: GitCLIWorkspaceService
) -> None:
    mock_run.return_value = ProcessResult(
        exit_code=0,
        stdout=b"output",
        stderr=b"",
        timed_out=False,
        truncated=False,
        duration_seconds=0.1
    )

    code, stdout, stderr = await git_service._run_git("status")

    assert code == 0
    assert stdout == "output"
    assert stderr == ""
    mock_run.assert_called_once_with(
        command=["git", "status"],
        cwd=str(git_service.workspace_root),
    )


@pytest.mark.anyio
@patch("forgeai.git.service.ProcessRunner.run", side_effect=FileNotFoundError)
async def test_run_git_missing_executable(
    mock_run: AsyncMock, git_service: GitCLIWorkspaceService
) -> None:
    with pytest.raises(GitUnavailableError, match="Git executable not found"):
        await git_service._run_git("status")


@pytest.mark.anyio
async def test_check_is_repo_fails(workspace_dir: Path) -> None:
    service = MockGitService(workspace_dir)
    service.mock_run_git.return_value = (128, "", "fatal: not a git repository")
    with pytest.raises(GitRepositoryNotFoundError):
        await service._check_is_repo()


# ==============================================================================
# Status Parsing
# ==============================================================================


@pytest.mark.anyio
async def test_status_parsing_clean(workspace_dir: Path) -> None:
    service = MockGitService(workspace_dir)
    service.mock_run_git.return_value = (0, "## main...origin/main\n", "")

    status = await service.get_status()
    assert status.branch == "main"
    assert status.is_clean is True
    assert len(status.staged_changes) == 0


@pytest.mark.anyio
async def test_status_parsing_dirty(workspace_dir: Path) -> None:
    service = MockGitService(workspace_dir)
    output = "## feat/task\n M tracked.py\n?? untracked.txt\nA  new.py\n"
    service.mock_run_git.return_value = (0, output, "")

    status = await service.get_status()
    assert status.branch == "feat/task"
    assert status.is_clean is False
    assert len(status.staged_changes) == 1
    assert status.staged_changes[0].path == "new.py"
    assert status.staged_changes[0].change_type == ChangeType.ADDED
    assert len(status.unstaged_changes) == 1
    assert status.unstaged_changes[0].path == "tracked.py"
    assert status.unstaged_changes[0].change_type == ChangeType.MODIFIED
    assert len(status.untracked_changes) == 1
    assert status.untracked_changes[0].path == "untracked.txt"
    assert status.untracked_changes[0].change_type == ChangeType.UNTRACKED


# ==============================================================================
# Branching
# ==============================================================================


def test_branch_sanitization(workspace_dir: Path) -> None:
    service = GitCLIWorkspaceService(workspace_dir)
    assert service._sanitize_branch_name("task-123") == "forgeai/task/task-123"
    assert service._sanitize_branch_name("!@#") == "forgeai/task/___"
    with pytest.raises(GitInvalidBranchError):
        service._sanitize_branch_name("")


@pytest.mark.anyio
async def test_create_branch_dirty(workspace_dir: Path) -> None:
    service = MockGitService(workspace_dir)
    # Mock status to be dirty
    service.mock_run_git.side_effect = [
        (0, "", ""),  # check_is_repo
        (0, "", ""),  # check_is_repo (from inspect_repository)
        (0, "## main\n M file.py\n", ""),  # get_status
    ]
    with pytest.raises(GitDirtyWorkspaceError):
        await service.create_branch("task")


@pytest.mark.anyio
async def test_create_branch_exists(workspace_dir: Path) -> None:
    service = MockGitService(workspace_dir)
    service.mock_run_git.side_effect = [
        (0, "", ""),  # check_is_repo
        (0, "", ""),  # check_is_repo (from inspect_repository)
        (0, "## main\n", ""),  # get_status (clean)
        (0, "", ""),  # show-ref (exists)
    ]
    with pytest.raises(GitBranchExistsError):
        await service.create_branch("task")


# ==============================================================================
# Diff parsing
# ==============================================================================


@pytest.mark.anyio
async def test_get_diff_parsing(workspace_dir: Path) -> None:
    service = MockGitService(workspace_dir)
    service.mock_run_git.side_effect = [
        (0, "", ""),  # check_is_repo
        (0, "+++ b/file.py", ""),  # diff
        (0, " 2 files changed, 5 insertions(+), 1 deletion(-)\n", ""),  # diff shortstat
    ]
    diff = await service.get_diff()
    assert diff.changed_files == 2
    assert diff.insertions == 5
    assert diff.deletions == 1
    assert diff.patch == "+++ b/file.py"
    assert diff.truncated is False


@pytest.mark.anyio
async def test_get_diff_truncation(workspace_dir: Path) -> None:
    service = MockGitService(workspace_dir)
    service._max_diff_bytes = 10  # Tiny limit
    service.mock_run_git.side_effect = [
        (0, "", ""),  # check_is_repo
        (0, "very long patch content", ""),  # diff
        (0, " 1 file changed\n", ""),  # diff shortstat
    ]
    diff = await service.get_diff()
    assert diff.truncated is True
    assert diff.patch == "very long \n...[TRUNCATED]..."


# ==============================================================================
# Staging & Sensitive Files
# ==============================================================================


def test_validate_path(workspace_dir: Path) -> None:
    service = GitCLIWorkspaceService(workspace_dir)

    # Allowed
    service._validate_path("src/main.py")
    service._validate_path("tests/test.py")

    # Forbidden: absolute
    with pytest.raises(GitStageError, match="Absolute paths"):
        service._validate_path(str(workspace_dir.parent / "file.py"))

    # Forbidden: path traversal
    with pytest.raises(GitStageError, match="Path traversal"):
        service._validate_path("../outside.py")

    # Forbidden: sensitive
    with pytest.raises(GitStageError, match="sensitive"):
        service._validate_path(".env")
    with pytest.raises(GitStageError, match="sensitive"):
        service._validate_path(".env.local")
    with pytest.raises(GitStageError, match="sensitive"):
        service._validate_path("config/secrets.pem")


@pytest.mark.anyio
async def test_stage_files_disallows_all(workspace_dir: Path) -> None:
    service = MockGitService(workspace_dir)
    service.mock_run_git.return_value = (0, "", "")

    with pytest.raises(GitStageError, match="Implicit"):
        await service.stage_files(["."])

    with pytest.raises(GitStageError, match="Implicit"):
        await service.stage_files(["-A"])


# ==============================================================================
# Commits
# ==============================================================================


@pytest.mark.anyio
async def test_commit_empty_message(workspace_dir: Path) -> None:
    service = MockGitService(workspace_dir)
    service.mock_run_git.return_value = (0, "", "")
    with pytest.raises(GitCommitError, match="cannot be empty"):
        await service.commit("   ", ["file.py"])


@pytest.mark.anyio
async def test_commit_no_paths(workspace_dir: Path) -> None:
    service = MockGitService(workspace_dir)
    service.mock_run_git.return_value = (0, "", "")
    with pytest.raises(GitCommitError, match="explicitly provided"):
        await service.commit("msg", [])
