"""Logic for excluding irrelevant or sensitive files from repository analysis."""

from pathlib import Path
from typing import Any

import pathspec

# Hardcoded directories that should always be ignored to prevent analyzing
# garbage/dependencies.
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".idea",
    ".vscode",
}

# Files that should be strictly excluded for security or irrelevance
SENSITIVE_OR_IRRELEVANT_FILES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.test",
    ".env.production",
}


class RepositoryIgnorer:
    """Evaluates whether files should be ignored based on defaults and .gitignore."""

    def __init__(self, repository_root: Path) -> None:
        """
        Initialize the ignorer.

        Args:
            repository_root: The root path of the repository.
        """
        self.root = repository_root
        self.spec = self._load_gitignore()

    def _load_gitignore(self) -> pathspec.PathSpec[Any] | None:
        gitignore_path = self.root / ".gitignore"
        if gitignore_path.is_file():
            try:
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                return pathspec.PathSpec.from_lines("gitignore", lines)
            except Exception:
                pass
        return None

    def should_ignore_dir(self, dir_name: str) -> bool:
        """Return True if the directory should be skipped entirely."""
        return dir_name in DEFAULT_IGNORE_DIRS

    def should_ignore_file(self, relative_path: str) -> bool:
        """Return True if the file should be excluded from analysis."""
        path_obj = Path(relative_path)

        # Check hardcoded sensitive/irrelevant files
        if path_obj.name in SENSITIVE_OR_IRRELEVANT_FILES:
            return True

        # Check gitignore
        if self.spec and self.spec.match_file(relative_path):
            return True

        # Check if any parent part of the file is in default ignore dirs
        # (as a fallback in case walk is bypassed)
        for part in path_obj.parts[:-1]:
            if part in DEFAULT_IGNORE_DIRS:
                return True

        return False
