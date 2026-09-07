"""Tool for listing files in the workspace."""

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


class ListFilesTool(BaseTool):
    """Tool that safely lists files in the workspace."""

    MAX_RESULTS = 1000

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_files",
            description=(
                "List files in the repository workspace. Excludes ignored and "
                "sensitive files."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Optional simple substring to filter file paths."
                        ),
                    }
                },
                "required": [],
            },
            capability=ToolCapability.READ_ONLY,
        )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        pattern = call.arguments.get("pattern")
        ignorer = RepositoryIgnorer(context.workspace_root)

        found_files = []
        try:
            for root, dirs, files in os.walk(context.workspace_root):
                current_dir = Path(root)

                # Filter directories in-place
                dirs[:] = [d for d in dirs if not ignorer.should_ignore_dir(d)]

                for file_name in files:
                    file_path = current_dir / file_name
                    rel_path = file_path.relative_to(context.workspace_root).as_posix()
                    if ignorer.should_ignore_file(rel_path):
                        continue

                    if pattern and pattern.lower() not in rel_path.lower():
                        continue

                    found_files.append(rel_path)

                    if len(found_files) >= self.MAX_RESULTS:
                        return ToolResult(
                            call_id=call.call_id,
                            success=True,
                            output={
                                "files": sorted(found_files),
                                "truncated": True,
                                "message": f"Truncated to {self.MAX_RESULTS} results.",
                            },
                        )

            return ToolResult(
                call_id=call.call_id,
                success=True,
                output={
                    "files": sorted(found_files),
                    "truncated": False,
                },
            )
        except Exception as e:
            raise ToolExecutionError(f"Failed to list files: {e}")
