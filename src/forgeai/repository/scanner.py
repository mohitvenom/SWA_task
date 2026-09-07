"""Repository scanner for building deterministic structural snapshots."""

import os
from pathlib import Path

from forgeai.repository.analyzer import PythonAnalyzer
from forgeai.repository.ignore import RepositoryIgnorer
from forgeai.repository.languages import detect_language
from forgeai.repository.models import (
    LanguageStats,
    RepositoryFile,
    RepositorySnapshot,
)

IMPORTANT_FILES_LOWER = {
    "readme.md",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "tox.ini",
    "setup.py",
    "setup.cfg",
}


class RepositoryScanner:
    """Scans a local repository directory to build a RepositorySnapshot."""

    def __init__(self, repository_root: str | Path) -> None:
        """
        Initialize the scanner.

        Args:
            repository_root: Absolute or relative path to the repository root.
        """
        self.root = Path(repository_root).resolve()
        self.ignorer = RepositoryIgnorer(self.root)

    def _is_important(self, relative_path: str) -> bool:
        path_obj = Path(relative_path)
        if path_obj.name.lower() in IMPORTANT_FILES_LOWER:
            return True
        # Also catch nested requirements files or CI configs if they appear
        if path_obj.parent.name == ".github" and path_obj.suffix in (".yml", ".yaml"):
            return True
        if path_obj.parent.name == "requirements" and path_obj.suffix == ".txt":
            return True
        return False

    def scan(self) -> RepositorySnapshot:
        """
        Perform the full directory scan and analysis.

        Returns:
            A populated RepositorySnapshot.
        """
        snapshot = RepositorySnapshot(repository_root=str(self.root))

        file_paths: list[Path] = []

        # 1. File Discovery
        for root, dirs, files in os.walk(self.root):
            # Filter directories in-place to prune the walk early
            dirs[:] = [d for d in dirs if not self.ignorer.should_ignore_dir(d)]

            for file_name in files:
                full_path = Path(root) / file_name

                # Protect against path traversal/symlink escapes
                try:
                    relative_path = str(full_path.relative_to(self.root)).replace(
                        os.sep, "/"
                    )
                except ValueError:
                    continue

                if not self.ignorer.should_ignore_file(relative_path):
                    file_paths.append(full_path)

        # Deterministic sorting
        file_paths.sort()
        snapshot.total_files_found = len(file_paths)

        # 2. File Analysis
        for full_path in file_paths:
            relative_path = str(full_path.relative_to(self.root)).replace(os.sep, "/")

            try:
                size = full_path.stat().st_size
            except OSError:
                continue

            lang = detect_language(relative_path)

            is_vendor = "vendor" in Path(relative_path).parts

            repo_file = RepositoryFile(
                relative_path=relative_path,
                extension=full_path.suffix,
                language=lang,
                size_bytes=size,
                is_generated_or_vendor=is_vendor,
            )

            # Update Language Stats
            if lang not in snapshot.language_stats:
                snapshot.language_stats[lang] = LanguageStats()
            snapshot.language_stats[lang].file_count += 1
            snapshot.language_stats[lang].total_bytes += size

            # Important files
            if self._is_important(relative_path):
                snapshot.important_files.append(relative_path)

            # Structural AST Analysis for Python
            if lang == "Python" and not is_vendor:
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    analyzer = PythonAnalyzer(relative_path)
                    analyzer.analyze(content)

                    repo_file.is_test = analyzer.is_test
                    if analyzer.is_test:
                        snapshot.test_files.append(relative_path)

                    snapshot.symbols.extend(analyzer.symbols)
                    snapshot.dependencies.extend(analyzer.dependencies)
                    snapshot.entry_points.extend(analyzer.entry_points)
                    snapshot.total_analyzed_files += 1
                except SyntaxError as e:
                    snapshot.analysis_errors[relative_path] = f"SyntaxError: {e}"
                except UnicodeDecodeError as e:
                    snapshot.analysis_errors[relative_path] = f"UnicodeDecodeError: {e}"
                except Exception as e:
                    snapshot.analysis_errors[relative_path] = f"Exception: {e}"
            else:
                # Basic heuristic test check for non-python files if needed
                if "test" in relative_path.lower():
                    repo_file.is_test = True
                    snapshot.test_files.append(relative_path)

            snapshot.files.append(repo_file)

        # Sort extracted collections for determinism
        snapshot.test_files.sort()
        snapshot.important_files.sort()
        # Custom sorts for models to ensure determinism
        snapshot.symbols.sort(key=lambda s: (s.file_path, s.line_number or 0, s.name))
        snapshot.dependencies.sort(key=lambda d: (d.file_path, d.name))
        snapshot.entry_points.sort(key=lambda e: (e.file_path, e.reason))

        return snapshot
