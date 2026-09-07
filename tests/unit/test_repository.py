"""Tests for the repository intelligence subsystem."""

from pathlib import Path

import pytest

from forgeai.repository.scanner import RepositoryScanner


@pytest.fixture
def repo_fixture(tmp_path: Path) -> Path:
    """Create a mock repository filesystem structure."""
    repo = tmp_path / "mock_repo"
    repo.mkdir()

    # Create .gitignore
    (repo / ".gitignore").write_text("*.log\nignored_dir/\n")

    # Create ignored dir
    ignored = repo / "ignored_dir"
    ignored.mkdir()
    (ignored / "secret.txt").write_text("should be ignored")

    # Create default ignored cache
    cache = repo / "__pycache__"
    cache.mkdir()
    (cache / "compiled.pyc").write_text("binary")

    # Create sensitive file
    (repo / ".env").write_text("SECRET=123")

    # Create important files
    (repo / "pyproject.toml").write_text("[project]\nname='mock'")
    (repo / "README.md").write_text("# Mock Repo")

    # Create source files
    src = repo / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "import os\n"
        "from typing import List\n"
        "class App:\n"
        "    pass\n"
        "def run():\n"
        "    pass\n"
        "if __name__ == '__main__':\n"
        "    run()\n"
    )

    (src / "malformed.py").write_text("def broken() -> :\n    pass\n")

    # Create tests
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text("def test_app():\n    assert True\n")

    return repo


def test_scanner_discovers_files(repo_fixture: Path) -> None:
    scanner = RepositoryScanner(repo_fixture)
    snapshot = scanner.scan()

    assert snapshot.repository_root == str(repo_fixture.resolve())
    assert snapshot.total_files_found > 0

    # Check that gitignore worked
    file_paths = [f.relative_path for f in snapshot.files]
    assert "ignored_dir/secret.txt" not in file_paths
    assert ".env" not in file_paths
    assert "__pycache__/compiled.pyc" not in file_paths

    # Check important files
    assert "pyproject.toml" in snapshot.important_files
    assert "README.md" in snapshot.important_files


def test_scanner_extracts_symbols_and_dependencies(repo_fixture: Path) -> None:
    scanner = RepositoryScanner(repo_fixture)
    snapshot = scanner.scan()

    # Check main.py symbols
    symbols = [s for s in snapshot.symbols if s.file_path == "src/main.py"]
    assert len(symbols) == 2
    assert any(s.name == "App" and s.symbol_type == "class" for s in symbols)
    assert any(s.name == "run" and s.symbol_type == "function" for s in symbols)

    # Check dependencies
    deps = [d for d in snapshot.dependencies if d.file_path == "src/main.py"]
    assert any(d.name == "os" for d in deps)
    assert any(d.name == "typing" for d in deps)


def test_scanner_detects_entry_points(repo_fixture: Path) -> None:
    scanner = RepositoryScanner(repo_fixture)
    snapshot = scanner.scan()

    entry_points = snapshot.entry_points
    assert len(entry_points) == 1
    assert entry_points[0].file_path == "src/main.py"
    assert 'if __name__ == "__main__":' in entry_points[0].reason


def test_scanner_handles_malformed_python(repo_fixture: Path) -> None:
    scanner = RepositoryScanner(repo_fixture)
    snapshot = scanner.scan()

    assert "src/malformed.py" in snapshot.analysis_errors
    assert "SyntaxError" in snapshot.analysis_errors["src/malformed.py"]


def test_scanner_language_stats(repo_fixture: Path) -> None:
    scanner = RepositoryScanner(repo_fixture)
    snapshot = scanner.scan()

    assert "Python" in snapshot.language_stats
    assert "Markdown" in snapshot.language_stats
    assert snapshot.language_stats["Python"].file_count >= 2


def test_scanner_test_detection(repo_fixture: Path) -> None:
    scanner = RepositoryScanner(repo_fixture)
    snapshot = scanner.scan()

    assert "tests/test_main.py" in snapshot.test_files
    test_file = next(
        f for f in snapshot.files if f.relative_path == "tests/test_main.py"
    )
    assert test_file.is_test is True
