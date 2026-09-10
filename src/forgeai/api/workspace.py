"""
API workspace authorization.

Validates that a caller-supplied workspace_root is safe to use before
any LLM or agent execution begins.  All rejections raise
:class:`WorkspaceAuthorizationError` which the API layer translates to a
structured 400/403 response without leaking internal path details.
"""

import logging
from pathlib import Path

from forgeai.config.settings import settings

logger = logging.getLogger("forgeai.api.workspace")


class WorkspaceAuthorizationError(Exception):
    """Raised when a workspace_root fails security validation.

    The *reason* attribute is safe to include in user-facing responses.
    The *detail* attribute contains fuller context for server logs only.
    """

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or reason


# Characters that are unambiguously path-traversal or injection attempts
# even before pathlib normalisation.
_TRAVERSAL_SEQUENCES = ("..", "//", "\\\\", "\x00", "%2e%2e", "%2f", "%5c")


def validate_workspace(raw_path: str) -> Path:
    """Validate and resolve a raw workspace_root string.

    Performs the following checks in order:

    1. Null-byte and traversal-sequence rejection (pre-parse)
    2. Parse into a :class:`~pathlib.Path`
    3. Must be absolute
    4. Must exist and be a directory (not a file or symlink to a file)
    5. Must not be a system-critical directory
    6. Resolve to a canonical path (resolves symlinks)
    7. If :attr:`~Settings.allowed_workspace_roots` is non-empty, the resolved
       path must be equal to or underneath one of the allowed roots

    Args:
        raw_path: The untrusted workspace_root string from the API caller.

    Returns:
        The canonically resolved :class:`~pathlib.Path`.

    Raises:
        WorkspaceAuthorizationError: If any validation step fails.
    """
    # 1. Pre-parse injection checks
    lower = raw_path.lower()
    for seq in _TRAVERSAL_SEQUENCES:
        if seq in lower or seq in raw_path:
            logger.warning("Workspace rejected: traversal sequence %r in input", seq)
            raise WorkspaceAuthorizationError(
                "workspace_root contains disallowed path sequences",
                detail=f"Traversal sequence {seq!r} detected in workspace_root",
            )

    # 2. Parse
    try:
        path = Path(raw_path)
    except Exception:
        raise WorkspaceAuthorizationError("workspace_root is not a valid path")

    # 3. Must be absolute
    if not path.is_absolute():
        raise WorkspaceAuthorizationError(
            "workspace_root must be an absolute path",
            detail=f"Relative path rejected: {raw_path!r}",
        )

    # 4. Must exist and be a real directory
    if not path.exists():
        raise WorkspaceAuthorizationError("workspace_root does not exist")

    if not path.is_dir():
        raise WorkspaceAuthorizationError(
            "workspace_root must be a directory, not a file",
        )

    # 5. Reject system-critical roots — operators should never point ForgeAI
    #    at /, /etc, /bin, C:\, C:\Windows, etc.
    try:
        resolved = path.resolve()
    except Exception:
        raise WorkspaceAuthorizationError("workspace_root could not be resolved")

    _CRITICAL_ROOTS = {
        Path("/"),
        Path("/etc"),
        Path("/bin"),
        Path("/usr"),
        Path("/boot"),
        Path("/root"),
        Path("/home"),
    }
    # Also reject Windows equivalents where applicable
    try:
        if resolved.drive and resolved == Path(resolved.drive + "\\"):
            raise WorkspaceAuthorizationError(
                "workspace_root is a filesystem root and cannot be used",
            )
    except Exception:
        pass

    if resolved in _CRITICAL_ROOTS:
        raise WorkspaceAuthorizationError(
            "workspace_root points to a system-critical directory",
        )

    # 6. (resolved above — used in step 7)

    # 7. Allowlist check — if the operator configured allowed roots, enforce them
    allowed_roots = settings.allowed_workspace_roots
    if allowed_roots:
        allowed_resolved = []
        for raw_allowed in allowed_roots:
            try:
                allowed_resolved.append(Path(raw_allowed).resolve())
            except Exception:
                logger.error("Invalid allowed_workspace_root in settings: %r", raw_allowed)

        for allowed in allowed_resolved:
            try:
                resolved.relative_to(allowed)
                break  # within this allowed root — OK
            except ValueError:
                continue
        else:
            logger.warning(
                "Workspace rejected: resolved path not in allowlist (allowlist has %d entries)",
                len(allowed_resolved),
            )
            raise WorkspaceAuthorizationError(
                "workspace_root is not within an authorized location",
                detail=f"Resolved path not in allowed_workspace_roots allowlist",
            )

    logger.debug("Workspace validated: %s", resolved)
    return resolved
