"""Tool for creating or writing files safely within the workspace."""

import os
import tempfile
from pathlib import Path

from forgeai.tools.base import BaseTool
from forgeai.tools.errors import SecurityViolationError
from forgeai.tools.models import (
    ToolCall,
    ToolCapability,
    ToolContext,
    ToolDefinition,
    ToolResult,
)
from forgeai.tools.repository.utils import resolve_safe_path


class WriteFileTool(BaseTool):
    """Tool that writes content to a file, safely within the workspace."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_file",
            description=(
                "Create a new file or overwrite an existing file. "
                "Only operates inside the trusted workspace."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The exact string content to write.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "If true, overwrites the file if it exists. "
                        "Defaults to false.",
                        "default": False,
                    },
                },
                "required": ["path", "content"],
            },
            capability=ToolCapability.MUTATION,
            is_dangerous=True,
        )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        raw_path = call.arguments.get("path")
        content = call.arguments.get("content")
        overwrite = call.arguments.get("overwrite", False)

        if not raw_path or not isinstance(raw_path, str):
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Argument 'path' must be a non-empty string.",
            )
        if not isinstance(content, str):
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Argument 'content' must be a string.",
            )

        try:
            target_path = resolve_safe_path(context.workspace_root, raw_path)
        except SecurityViolationError as e:
            # We raise security violations to immediately fail the agent session
            raise e
        except ValueError as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

        # Check existing
        existed = target_path.exists()
        if existed and not overwrite:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"File already exists: {raw_path}. "
                "Set 'overwrite=true' to overwrite.",
            )

        # Create parent directories
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"Failed to create directories: {e}",
            )

        try:
            content_bytes = content.encode("utf-8")
        except UnicodeEncodeError as e:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"Content encoding error (must be utf-8): {e}",
            )

        # Atomic write
        temp_file = None
        try:
            fd, temp_path_str = tempfile.mkstemp(
                dir=str(target_path.parent), text=False
            )
            temp_file = Path(temp_path_str)
            with os.fdopen(fd, "wb") as f:
                f.write(content_bytes)
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_file, target_path)

            return ToolResult(
                call_id=call.call_id,
                success=True,
                output={
                    "operation": "write",
                    "path": str(
                        target_path.relative_to(context.workspace_root).as_posix()
                    ),
                    "created": not existed,
                    "overwritten": existed,
                    "bytes_written": len(content_bytes),
                },
            )
        except Exception as e:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"Filesystem error during write: {e}",
            )
