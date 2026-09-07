"""Integration tests for the Git workspace subsystem.

These tests use actual temporary Git repositories to verify subprocess interactions.
"""

import subprocess
from pathlib import Path

import pytest

from forgeai.git.errors import (
    GitDirtyWorkspaceError,
    GitStageError,
)
from forgeai.git.models import ChangeType
from forgeai.git.service import GitCLIWorkspaceService


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """Provides a temporary, initialized Git repository."""
    d = tmp_path / "repo"
    d.mkdir()

    # Initialize repo
    subprocess.run(["git", "init"], cwd=d, check=True, capture_output=True)

    # Configure local identity for tests
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=d,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=d,
        check=True,
        capture_output=True,
    )

    return d


@pytest.fixture
def git_service(repo_dir: Path) -> GitCLIWorkspaceService:
    return GitCLIWorkspaceService(repo_dir)


@pytest.mark.anyio
async def test_lifecycle_1_initialization(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    """TEST 1: Initialize, create initial commit, verify status."""

    # We must have at least one commit to have a valid branch 'main'/'master'
    (repo_dir / "README.md").write_text("Hello")
    subprocess.run(
        ["git", "add", "README.md"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    status = await git_service.get_status()
    assert status.is_clean is True
    assert status.branch in ("main", "master")


@pytest.mark.anyio
async def test_lifecycle_2_branch_creation(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    """TEST 2: Create task branch and verify."""
    (repo_dir / "README.md").write_text("Hello")
    subprocess.run(
        ["git", "add", "README.md"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    branch = await git_service.create_branch("my-task-123")
    assert branch.name == "forgeai/task/my-task-123"

    status = await git_service.get_status()
    assert status.branch == "forgeai/task/my-task-123"


@pytest.mark.anyio
async def test_lifecycle_3_modifications_and_diff(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    """TEST 3: Modify tracked file and verify diff."""
    (repo_dir / "file.py").write_text("a = 1\n")
    subprocess.run(
        ["git", "add", "file.py"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Init"], cwd=repo_dir, check=True, capture_output=True
    )

    (repo_dir / "file.py").write_text("a = 2\nb = 3\n")

    status = await git_service.get_status()
    assert status.is_clean is False
    assert len(status.unstaged_changes) == 1
    assert status.unstaged_changes[0].change_type == ChangeType.MODIFIED

    diff = await git_service.get_diff()
    assert diff.changed_files == 1
    assert diff.insertions == 2
    assert diff.deletions == 1
    assert "-a = 1" in diff.patch


@pytest.mark.anyio
async def test_lifecycle_4_untracked_files(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    """TEST 4: Create untracked file."""
    (repo_dir / "file.py").write_text("a = 1\n")
    subprocess.run(
        ["git", "add", "file.py"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Init"], cwd=repo_dir, check=True, capture_output=True
    )

    (repo_dir / "untracked.txt").write_text("hello")

    status = await git_service.get_status()
    assert len(status.untracked_changes) == 1
    assert status.untracked_changes[0].path == "untracked.txt"
    assert status.untracked_changes[0].change_type == ChangeType.UNTRACKED


@pytest.mark.anyio
async def test_lifecycle_5_and_6_staging_and_commit(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    """TEST 5 & 6: Explicit staging and commit."""
    (repo_dir / "file.py").write_text("a = 1\n")
    subprocess.run(
        ["git", "add", "file.py"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Init"], cwd=repo_dir, check=True, capture_output=True
    )

    (repo_dir / "file.py").write_text("a = 2\n")
    (repo_dir / "ignore.py").write_text("b = 2\n")

    commit = await git_service.commit("Update a", ["file.py"])

    assert commit.commit_hash != ""
    assert commit.message == "Update a"

    status = await git_service.get_status()
    assert len(status.unstaged_changes) == 0
    assert len(status.untracked_changes) == 1
    assert status.untracked_changes[0].path == "ignore.py"


@pytest.mark.anyio
async def test_lifecycle_7_rollback(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    """TEST 7: Rollback tracked file preserves untracked file."""
    (repo_dir / "file.py").write_text("a = 1\n")
    subprocess.run(
        ["git", "add", "file.py"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Init"], cwd=repo_dir, check=True, capture_output=True
    )

    (repo_dir / "file.py").write_text("a = 2\n")
    (repo_dir / "untracked.txt").write_text("test")

    await git_service.rollback_files(["file.py"])

    assert (repo_dir / "file.py").read_text() == "a = 1\n"
    assert (repo_dir / "untracked.txt").exists()


@pytest.mark.anyio
async def test_lifecycle_8_checkpoints(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    """TEST 8: Checkpoint restore semantics."""
    (repo_dir / "file.py").write_text("a = 1\n")
    subprocess.run(
        ["git", "add", "file.py"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Init"], cwd=repo_dir, check=True, capture_output=True
    )

    checkpoint = await git_service.create_checkpoint("task-1")

    (repo_dir / "file.py").write_text("a = 2\n")
    await git_service.commit("Second", ["file.py"])

    await git_service.restore_checkpoint(checkpoint)

    assert (repo_dir / "file.py").read_text() == "a = 1\n"


@pytest.mark.anyio
async def test_lifecycle_9_invalid_branch(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    """TEST 9: Branch creation dirty rejection."""
    (repo_dir / "file.py").write_text("a = 1\n")
    subprocess.run(
        ["git", "add", "file.py"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Init"], cwd=repo_dir, check=True, capture_output=True
    )

    (repo_dir / "file.py").write_text("dirty")

    with pytest.raises(GitDirtyWorkspaceError):
        await git_service.create_branch("task-1")


@pytest.mark.anyio
async def test_lifecycle_10_12_security(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    """TEST 10, 11, 12: Staging security."""
    with pytest.raises(GitStageError, match="sensitive"):
        await git_service.stage_files([".env"])

    with pytest.raises(GitStageError, match="Absolute paths"):
        await git_service.stage_files([str(repo_dir.parent / "file.py")])

    with pytest.raises(GitStageError, match="traversal"):
        await git_service.stage_files(["../file.py"])


# ==============================================================================
# HARDENING PASS TESTS (A - L)
# ==============================================================================


@pytest.mark.anyio
async def test_A_commit_pre_staged_unrelated_file_rejects(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    (repo_dir / "file_b.py").write_text("b=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file_a.py").write_text("a=2\n")
    (repo_dir / "file_b.py").write_text("b=2\n")
    subprocess.run(["git", "add", "file_b.py"], cwd=repo_dir, check=True)

    from forgeai.git.errors import GitCommitError

    with pytest.raises(GitCommitError, match="outside the explicitly requested paths"):
        await git_service.commit("Update A", ["file_a.py"])

    # Verify no commit was created (still 1 commit)
    code, out, _ = await git_service._run_git("rev-list", "--count", "HEAD")
    assert out.strip() == "1"


@pytest.mark.anyio
async def test_B_commit_exactly_requested_file(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file_a.py").write_text("a=2\n")
    await git_service.commit("Update A", ["file_a.py"])

    status = await git_service.get_status()
    assert status.is_clean is True


@pytest.mark.anyio
async def test_C_commit_pre_staged_requested_file_succeeds(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file_a.py").write_text("a=2\n")
    subprocess.run(["git", "add", "file_a.py"], cwd=repo_dir, check=True)

    await git_service.commit("Update A", ["file_a.py"])
    status = await git_service.get_status()
    assert status.is_clean is True


@pytest.mark.anyio
async def test_D_commit_subset_rejects(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    (repo_dir / "file_b.py").write_text("b=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file_a.py").write_text("a=2\n")
    (repo_dir / "file_b.py").write_text("b=2\n")
    subprocess.run(["git", "add", "file_a.py", "file_b.py"], cwd=repo_dir, check=True)

    from forgeai.git.errors import GitCommitError

    with pytest.raises(GitCommitError, match="outside the explicitly requested paths"):
        await git_service.commit("Update A", ["file_a.py"])


@pytest.mark.anyio
async def test_E_commit_missing_file_rejects(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    from forgeai.git.errors import GitStageError

    with pytest.raises(GitStageError):
        await git_service.commit("Update", ["missing.py"])


@pytest.mark.anyio
async def test_F_clean_repo_checkpoint_contains_head(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    code, expected_hash, _ = await git_service._run_git("rev-parse", "HEAD")
    checkpoint = await git_service.create_checkpoint("task-1")
    assert checkpoint.commit_hash == expected_hash.strip()


@pytest.mark.anyio
async def test_G_dirty_tracked_file_rejects_checkpoint(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file_a.py").write_text("a=2\n")
    with pytest.raises(GitDirtyWorkspaceError):
        await git_service.create_checkpoint("task-1")


@pytest.mark.anyio
async def test_H_staged_change_rejects_checkpoint(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file_a.py").write_text("a=2\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    with pytest.raises(GitDirtyWorkspaceError):
        await git_service.create_checkpoint("task-1")


@pytest.mark.anyio
async def test_I_untracked_file_rejects_checkpoint(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file_b.py").write_text("b=1\n")
    with pytest.raises(GitDirtyWorkspaceError):
        await git_service.create_checkpoint("task-1")


@pytest.mark.anyio
async def test_J_checkpoint_restore_returns_head(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")

    (repo_dir / "file_a.py").write_text("a=2\n")
    await git_service.commit("Update A", ["file_a.py"])

    await git_service.restore_checkpoint(checkpoint)
    assert (repo_dir / "file_a.py").read_text() == "a=1\n"


@pytest.mark.anyio
async def test_K_untracked_file_survives_checkpoint_restore(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")

    (repo_dir / "untracked.py").write_text("test\n")

    await git_service.restore_checkpoint(checkpoint)
    assert (repo_dir / "untracked.py").exists()


@pytest.mark.anyio
async def test_L_dirty_tracked_rejects_restore(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")

    (repo_dir / "file_a.py").write_text("a=2\n")

    from forgeai.git.errors import GitRollbackError

    with pytest.raises(
        GitRollbackError, match="uncommitted tracked changes that would be destroyed"
    ):
        await git_service.restore_checkpoint(checkpoint)


@pytest.mark.anyio
async def test_M_untracked_file_conflict_rejects_restore(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")

    # Remove file_a.py and commit so it's gone from HEAD
    subprocess.run(["git", "rm", "file_a.py"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "remove file_a"], cwd=repo_dir, check=True)

    # Now create an untracked file at the exact same path that the checkpoint has it
    (repo_dir / "file_a.py").write_text("untracked\n")

    from forgeai.git.errors import GitRollbackError

    with pytest.raises(
        GitRollbackError,
        match="conflicts with the target checkpoint tree and would be overwritten",
    ):
        await git_service.restore_checkpoint(checkpoint)

    # Verify the untracked file remains
    assert (repo_dir / "file_a.py").read_text() == "untracked\n"


@pytest.mark.anyio
async def test_N_checkpoint_nonexistent_commit_hash(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")
    # Mutate to a fake hash
    checkpoint.commit_hash = "0000000000000000000000000000000000000000"

    from forgeai.git.errors import GitRollbackError

    with pytest.raises(GitRollbackError, match="Invalid checkpoint commit hash"):
        await git_service.restore_checkpoint(checkpoint)


@pytest.mark.anyio
async def test_O_checkpoint_invalid_commit_type(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")

    # Find a tree or blob hash
    proc = subprocess.run(
        ["git", "ls-tree", "HEAD"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    blob_hash = proc.stdout.split()[2]

    checkpoint.commit_hash = blob_hash

    from forgeai.git.errors import GitRollbackError

    with pytest.raises(GitRollbackError, match="Invalid checkpoint commit hash"):
        await git_service.restore_checkpoint(checkpoint)


@pytest.mark.anyio
async def test_P_checkpoint_invalid_branch(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")
    checkpoint.branch = "nonexistent-branch"

    from forgeai.git.errors import GitRollbackError

    with pytest.raises(GitRollbackError, match="Invalid checkpoint branch"):
        await git_service.restore_checkpoint(checkpoint)


@pytest.mark.anyio
async def test_Q_untracked_dir_conflict_rejects_restore(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "src" / "auth").mkdir(parents=True)
    (repo_dir / "src" / "auth" / "login.py").write_text("login\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")

    # Remove it completely so the directory becomes untracked when we add a new file
    subprocess.run(["git", "rm", "-r", "src"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "rm"], cwd=repo_dir, check=True)

    # Create untracked file in the same hierarchy
    (repo_dir / "src" / "auth").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "auth" / "custom.txt").write_text("untracked\n")

    from forgeai.git.errors import GitRollbackError

    with pytest.raises(
        GitRollbackError, match="conflicts with the target checkpoint tree"
    ):
        await git_service.restore_checkpoint(checkpoint)


@pytest.mark.anyio
async def test_S_non_conflicting_untracked_survives(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "src" / "auth").mkdir(parents=True)
    (repo_dir / "src" / "auth" / "login.py").write_text("login\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")

    (repo_dir / "docs").mkdir()
    (repo_dir / "docs" / "tmp.txt").write_text("tmp\n")

    await git_service.restore_checkpoint(checkpoint)
    assert (repo_dir / "docs" / "tmp.txt").exists()


@pytest.mark.anyio
async def test_T_checkpoint_branch_descendant_allowed(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")

    (repo_dir / "file_a.py").write_text("a=2\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "update"], cwd=repo_dir, check=True)

    # The branch has advanced, but the checkpoint commit is still an ancestor
    await git_service.restore_checkpoint(checkpoint)
    assert (repo_dir / "file_a.py").read_text() == "a=1\n"


@pytest.mark.anyio
async def test_U_checkpoint_unrelated_history_rejected(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    # Create orphan branch
    subprocess.run(["git", "checkout", "--orphan", "other"], cwd=repo_dir, check=True)
    (repo_dir / "file_b.py").write_text("b=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "other"], cwd=repo_dir, check=True)

    code, out, _ = await git_service._run_git("rev-parse", "HEAD")
    other_commit = out.strip()

    subprocess.run(["git", "checkout", "master"], cwd=repo_dir, check=True)

    checkpoint = await git_service.create_checkpoint("task-1")
    checkpoint.commit_hash = other_commit

    from forgeai.git.errors import GitRollbackError

    with pytest.raises(GitRollbackError, match="not reachable from branch"):
        await git_service.restore_checkpoint(checkpoint)


@pytest.mark.anyio
async def test_W_commit_subset_all(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    (repo_dir / "file_b.py").write_text("b=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file_a.py").write_text("a=2\n")
    (repo_dir / "file_b.py").write_text("b=2\n")

    await git_service.commit("Update both", ["file_a.py", "file_b.py"])
    status = await git_service.get_status()
    assert status.is_clean is True


@pytest.mark.anyio
async def test_X_commit_external_stage_rejected(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    (repo_dir / "file_b.py").write_text("b=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file_a.py").write_text("a=2\n")
    (repo_dir / "file_b.py").write_text("b=2\n")
    subprocess.run(["git", "add", "file_b.py"], cwd=repo_dir, check=True)

    from forgeai.git.errors import GitCommitError

    with pytest.raises(GitCommitError, match="outside the explicitly requested paths"):
        await git_service.commit("Update A", ["file_a.py"])


@pytest.mark.anyio
async def test_Y_commit_subset_partial(
    repo_dir: Path, git_service: GitCLIWorkspaceService
) -> None:
    (repo_dir / "file_a.py").write_text("a=1\n")
    (repo_dir / "file_b.py").write_text("b=1\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file_a.py").write_text("a=2\n")
    (repo_dir / "file_b.py").write_text("b=2\n")

    await git_service.commit("Update A", ["file_a.py"])

    status = await git_service.get_status()
    assert status.is_clean is False
    assert len(status.unstaged_changes) == 1
    assert status.unstaged_changes[0].path == "file_b.py"
