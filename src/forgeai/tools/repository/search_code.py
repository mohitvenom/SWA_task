"""Tool for searching code across the workspace."""

import os
from pathlib import Path

from forgeai.repository.ignore import RepositoryIgnorer
from forgeai.tools.base import BaseTool
from forgeai.tools.errors import ToolExecutionError
from forgeai.tools.models import (
    ToolCall,
    ToolCapability,
    ToolContext,
    ToolDefinition,
    ToolResult,
)


class SearchCodeTool(BaseTool):
    """Tool that safely searches for text across non-ignored files."""

    MAX_RESULTS = 100
    MAX_LINE_LENGTH = 150

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_code",
            description="Search for a text query across all non-ignored files.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The text substring to search for.",
                    },
                    "path_pattern": {
                        "type": "string",
                        "description": (
                            "Optional simple substring to filter file paths."
                        ),
                    },
                },
                "required": ["query"],
            },
            capability=ToolCapability.READ_ONLY,
        )

    def _is_binary(self, path: Path) -> bool:
        try:
            with open(path, "rb") as f:
                chunk = f.read(1024)
                textchars = bytearray(
                    {7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F}
                )
                if not chunk:
                    return False
                return bool(chunk.translate(None, textchars))
        except Exception:
            return True

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        query = call.arguments.get("query")
        if not query:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Missing required argument: query",
            )

        path_pattern = call.arguments.get("path_pattern")
        ignorer = RepositoryIgnorer(context.workspace_root)

        results = []

        try:
            for root, dirs, files in os.walk(context.workspace_root):
                current_dir = Path(root)

                # Filter directories in-place
                dirs[:] = [d for d in dirs if not ignorer.should_ignore_dir(d)]

                for file_name in sorted(files):
                    file_path = current_dir / file_name
                    rel_path = file_path.relative_to(context.workspace_root).as_posix()

                    if ignorer.should_ignore_file(rel_path):
                        continue

                    if path_pattern and path_pattern.lower() not in rel_path.lower():
                        continue

                    if self._is_binary(file_path):
                        continue

                    try:
                        with open(
                            file_path, "r", encoding="utf-8", errors="replace"
                        ) as f:
                            for i, line in enumerate(f):
                                if query in line:
                                    content = line.strip()
                                    if len(content) > self.MAX_LINE_LENGTH:
                                        content = (
                                            content[: self.MAX_LINE_LENGTH] + "..."
                                        )

                                    results.append(
                                        {
                                            "path": rel_path,
                                            "line": i + 1,
                                            "content": content,
                                        }
                                    )

                                    if len(results) >= self.MAX_RESULTS:
                                        return ToolResult(
                                            call_id=call.call_id,
                                            success=True,
                                            output={
                                                "results": results,
                                                "truncated": True,
                                                "message": (
                                                    f"Truncated to {self.MAX_RESULTS} "
                                                    "results."
                                                ),
                                            },
                                        )
                    except Exception:
                        continue  # Ignore unreadable files

            return ToolResult(
                call_id=call.call_id,
                success=True,
                output={
                    "results": results,
                    "truncated": False,
                },
            )
        except Exception as e:
            raise ToolExecutionError(f"Failed to search code: {e}")
