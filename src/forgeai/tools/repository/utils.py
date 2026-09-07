"""Utility functions for repository tools."""

from pathlib import Path

from forgeai.repository.ignore import SENSITIVE_OR_IRRELEVANT_FILES
from forgeai.tools.errors import PathTraversalError, SecurityViolationError


def resolve_safe_path(workspace_root: Path, path_str: str) -> Path:
    """
    Safely resolve a path string against the workspace root.

    Ensures that the resulting path is strictly within the workspace root
    and does not point to sensitive files.

    Args:
        workspace_root: The root of the workspace.
        path_str: The requested path (should be relative).

    Returns:
        The safely resolved absolute Path.

    Raises:
        PathTraversalError: If the path escapes the workspace root.
        SecurityViolationError: If the path is absolute, outside the root, or sensitive.
    """
    try:
        path = Path(path_str)
    except Exception as e:
        raise SecurityViolationError(f"Invalid path format: {e}")

    # Prevent absolute paths outside the workspace
    if path.is_absolute():
        try:
            path.relative_to(workspace_root)
        except ValueError:
            raise SecurityViolationError(
                f"Absolute paths outside the workspace are forbidden: {path_str}"
            )
        resolved_path = path.resolve()
    else:
        resolved_path = (workspace_root / path).resolve()

    # Prevent path traversal
    try:
        resolved_path.relative_to(workspace_root.resolve())
    except ValueError:
        raise PathTraversalError(
            f"Path traversal detected. Path escapes workspace root: {path_str}"
        )

    # Reject sensitive files
    if resolved_path.name in SENSITIVE_OR_IRRELEVANT_FILES:
        raise SecurityViolationError(
            f"Access to sensitive or irrelevant file forbidden: {resolved_path.name}"
        )

    # Note: We do not check if it is in .gitignore here, as that is done by
    # RepositoryIgnorer for tools like search and list, but single file read
    # might allow reading a non-sensitive ignored file if explicitly requested.

    return resolved_path
