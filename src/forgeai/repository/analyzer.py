"""Structural and dependency analyzer for repository files."""

import ast
from pathlib import Path

from forgeai.repository.models import (
    RepositoryDependency,
    RepositoryEntryPoint,
    RepositorySymbol,
)


class PythonAnalyzer:
    """Analyzes Python source files using the built-in ast module."""

    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.symbols: list[RepositorySymbol] = []
        self.dependencies: list[RepositoryDependency] = []
        self.entry_points: list[RepositoryEntryPoint] = []
        self.is_test = False

    def analyze(self, content: str) -> None:
        """
        Parse and analyze the Python source code.

        Args:
            content: The Python source code.

        Raises:
            SyntaxError: If the code cannot be parsed.
        """
        tree = ast.parse(content, filename=self.relative_path)

        path_obj = Path(self.relative_path)
        name_stem = path_obj.stem
        self.is_test = (
            name_stem.startswith("test_")
            or name_stem.endswith("_test")
            or "tests" in path_obj.parts
        )

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self.symbols.append(
                    RepositorySymbol(
                        name=node.name,
                        symbol_type="class",
                        file_path=self.relative_path,
                        line_number=node.lineno,
                    )
                )
                if "test" in node.name.lower():
                    self.is_test = True

            elif isinstance(node, ast.FunctionDef):
                self.symbols.append(
                    RepositorySymbol(
                        name=node.name,
                        symbol_type="function",
                        file_path=self.relative_path,
                        line_number=node.lineno,
                    )
                )
                if "test" in node.name.lower():
                    self.is_test = True

            elif isinstance(node, ast.AsyncFunctionDef):
                self.symbols.append(
                    RepositorySymbol(
                        name=node.name,
                        symbol_type="async_function",
                        file_path=self.relative_path,
                        line_number=node.lineno,
                    )
                )
                if "test" in node.name.lower():
                    self.is_test = True

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.dependencies.append(
                        RepositoryDependency(
                            name=alias.name,
                            file_path=self.relative_path,
                        )
                    )

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.dependencies.append(
                        RepositoryDependency(
                            name=node.module,
                            file_path=self.relative_path,
                        )
                    )

            elif isinstance(node, ast.If):
                # Heuristic for if __name__ == "__main__":
                if self._is_name_main(node.test):
                    self.entry_points.append(
                        RepositoryEntryPoint(
                            file_path=self.relative_path,
                            reason='Found `if __name__ == "__main__":` block.',
                            confidence=0.9,
                        )
                    )

    def _is_name_main(self, test_node: ast.expr) -> bool:
        if isinstance(test_node, ast.Compare):
            if isinstance(test_node.left, ast.Name) and test_node.left.id == "__name__":
                if len(test_node.comparators) == 1 and isinstance(
                    test_node.comparators[0], ast.Constant
                ):
                    if test_node.comparators[0].value == "__main__":
                        return True
        return False
