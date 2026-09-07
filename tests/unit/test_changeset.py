"""Unit tests for ChangeSetPolicy."""

from pathlib import Path

import pytest

from forgeai.agents.models import (
    ChangeOperation,
    ChangeSet,
    ChangeSetStatus,
    FileChange,
    ScopeExpansionDecision,
    ScopeExpansionReason,
)
from forgeai.config.settings import settings
from forgeai.policies.changeset import ChangeSetPolicy


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """Provide a temporary workspace root."""
    return tmp_path


@pytest.fixture
def policy(workspace_root: Path) -> ChangeSetPolicy:
    """Provide a ChangeSetPolicy instance."""
    # Ensure a consistent limit for testing
    settings.coding_max_changed_files = 5
    return ChangeSetPolicy(workspace_root)


def test_authorize_change_set_basic(workspace_root: Path, policy: ChangeSetPolicy) -> None:
    """Test basic authorization of initial and discovered files."""
    proposed = ChangeSet(
        objective="Extract module",
        initial_files=[
            FileChange(file_path="src/main.py", operation=ChangeOperation.MODIFY, rationale=""),
        ],
        discovered_files=[
            FileChange(file_path="src/helper.py", operation=ChangeOperation.CREATE, rationale=""),
            FileChange(file_path="src/old_helper.py", operation=ChangeOperation.DELETE, rationale=""),
        ]
    )
    
    authorized = policy.authorize_change_set(proposed, excluded_files=[])
    
    assert authorized.status == ChangeSetStatus.AUTHORIZED
    assert len(authorized.authorized_files) == 3
    assert "src/main.py" in authorized.modified_files
    assert "src/helper.py" in authorized.created_files
    assert "src/old_helper.py" in authorized.deleted_files
    assert len(authorized.expansion_history) == 3
    for record in authorized.expansion_history:
        assert record.decision == ScopeExpansionDecision.APPROVED


def test_authorize_change_set_absolute_path_rejection(workspace_root: Path, policy: ChangeSetPolicy) -> None:
    """Test that absolute paths are rejected."""
    proposed = ChangeSet(
        objective="Hack",
        initial_files=[
            FileChange(file_path="/etc/passwd", operation=ChangeOperation.MODIFY, rationale=""),
        ]
    )
    
    authorized = policy.authorize_change_set(proposed, excluded_files=[])
    
    assert authorized.status == ChangeSetStatus.REJECTED
    assert len(authorized.authorized_files) == 0
    assert len(authorized.expansion_history) == 1
    assert authorized.expansion_history[0].decision == ScopeExpansionDecision.REJECTED_OUT_OF_BOUNDS


def test_authorize_change_set_parent_traversal_rejection(workspace_root: Path, policy: ChangeSetPolicy) -> None:
    """Test that parent traversals are rejected."""
    proposed = ChangeSet(
        objective="Hack",
        initial_files=[
            FileChange(file_path="../outside.py", operation=ChangeOperation.MODIFY, rationale=""),
        ]
    )
    
    authorized = policy.authorize_change_set(proposed, excluded_files=[])
    
    assert authorized.status == ChangeSetStatus.REJECTED
    assert len(authorized.authorized_files) == 0
    assert len(authorized.expansion_history) == 1
    assert authorized.expansion_history[0].decision == ScopeExpansionDecision.REJECTED_OUT_OF_BOUNDS


def test_authorize_change_set_sensitive_rejection(workspace_root: Path, policy: ChangeSetPolicy) -> None:
    """Test that sensitive files are rejected."""
    proposed = ChangeSet(
        objective="Hack",
        initial_files=[
            FileChange(file_path=".env.production", operation=ChangeOperation.MODIFY, rationale=""),
            FileChange(file_path="secret_rsa", operation=ChangeOperation.MODIFY, rationale=""),
        ]
    )
    
    authorized = policy.authorize_change_set(proposed, excluded_files=[])
    
    assert authorized.status == ChangeSetStatus.REJECTED
    assert len(authorized.authorized_files) == 0
    assert len(authorized.expansion_history) == 2
    for record in authorized.expansion_history:
        assert record.decision == ScopeExpansionDecision.REJECTED_SENSITIVE


def test_authorize_change_set_excluded_rejection(workspace_root: Path, policy: ChangeSetPolicy) -> None:
    """Test that excluded files and directories are rejected."""
    proposed = ChangeSet(
        objective="Modify excluded",
        initial_files=[
            FileChange(file_path="src/protected.py", operation=ChangeOperation.MODIFY, rationale=""),
            FileChange(file_path="vendor/lib.py", operation=ChangeOperation.MODIFY, rationale=""),
        ]
    )
    
    authorized = policy.authorize_change_set(proposed, excluded_files=["src/protected.py", "vendor"])
    
    assert authorized.status == ChangeSetStatus.REJECTED
    assert len(authorized.authorized_files) == 0
    assert len(authorized.expansion_history) == 2
    for record in authorized.expansion_history:
        assert record.decision == ScopeExpansionDecision.REJECTED_EXCLUDED


def test_authorize_change_set_duplicate_rejection(workspace_root: Path, policy: ChangeSetPolicy) -> None:
    """Test that duplicate requests for the same file only authorize it once."""
    proposed = ChangeSet(
        objective="Duplicates",
        initial_files=[
            FileChange(file_path="src/main.py", operation=ChangeOperation.MODIFY, rationale=""),
        ],
        discovered_files=[
            FileChange(file_path="src/main.py", operation=ChangeOperation.MODIFY, rationale=""),
        ]
    )
    
    authorized = policy.authorize_change_set(proposed, excluded_files=[])
    
    assert authorized.status == ChangeSetStatus.AUTHORIZED
    assert len(authorized.authorized_files) == 1
    assert len(authorized.expansion_history) == 2
    assert authorized.expansion_history[0].decision == ScopeExpansionDecision.APPROVED
    assert authorized.expansion_history[1].decision == ScopeExpansionDecision.REJECTED_DUPLICATE


def test_authorize_change_set_limit_exceeded(workspace_root: Path, policy: ChangeSetPolicy) -> None:
    """Test that file limits are strictly enforced."""
    initials = []
    # settings.coding_max_changed_files = 5 for this fixture
    for i in range(10):
        initials.append(FileChange(file_path=f"src/file_{i}.py", operation=ChangeOperation.MODIFY, rationale=""))
        
    proposed = ChangeSet(
        objective="Too many files",
        initial_files=initials
    )
    
    authorized = policy.authorize_change_set(proposed, excluded_files=[])
    
    assert authorized.status == ChangeSetStatus.AUTHORIZED
    assert len(authorized.authorized_files) == 5
    
    # First 5 approved, last 5 rejected
    approvals = [r for r in authorized.expansion_history if r.decision == ScopeExpansionDecision.APPROVED]
    rejections = [r for r in authorized.expansion_history if r.decision == ScopeExpansionDecision.REJECTED_LIMIT_EXCEEDED]
    
    assert len(approvals) == 5
    assert len(rejections) == 5
