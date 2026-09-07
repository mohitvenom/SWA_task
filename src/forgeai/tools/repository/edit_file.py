"""Tool for exact search-and-replace editing in files safely within the workspace."""

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


class EditFileTool(BaseTool):
    """Tool that edits an existing file using strict exact replacement."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="edit_file",
            description=(
                "Edit an existing file safely using exact text replacement. "
                "Fails if the expected text does not exist or the count does not match."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file.",
                    },
                    "expected_text": {
                        "type": "string",
                        "description": "The exact string block currently in the file "
                        "to replace.",
                    },
                    "replacement_text": {
                        "type": "string",
                        "description": "The new string block to insert.",
                    },
                    "expected_count": {
                        "type": "integer",
                        "description": "The exact number of times expected_text should "
                        "be found (usually 1).",
                    },
                },
                "required": [
                    "path",
                    "expected_text",
                    "replacement_text",
                    "expected_count",
                ],
            },
            capability=ToolCapability.MUTATION,
            is_dangerous=True,
        )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        raw_path = call.arguments.get("path")
        expected_text = call.arguments.get("expected_text")
        replacement_text = call.arguments.get("replacement_text")
        expected_count = call.arguments.get("expected_count")

        if not raw_path or not isinstance(raw_path, str):
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Argument 'path' must be a non-empty string.",
            )
        if not isinstance(expected_text, str) or not isinstance(replacement_text, str):
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Arguments 'expected_text' and 'replacement_text' must be "
                "strings.",
            )
        if not isinstance(expected_count, int) or expected_count < 1:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Argument 'expected_count' must be a positive integer.",
            )

        try:
            target_path = resolve_safe_path(context.workspace_root, raw_path)
        except SecurityViolationError as e:
            raise e
        except ValueError as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

        if not target_path.exists():
            return ToolResult(
                call_id=call.call_id, success=False, error=f"File not found: {raw_path}"
            )

        try:
            original_content = target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="File is not valid UTF-8 and cannot be edited as text.",
            )
        except Exception as e:
            return ToolResult(
                call_id=call.call_id, success=False, error=f"Failed to read file: {e}"
            )

        actual_count = original_content.count(expected_text)
        if actual_count != expected_count:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=(
                    f"Occurrence mismatch: expected '{expected_text}' to appear "
                    f"{expected_count} times, "
                    f"but found {actual_count} times."
                ),
            )

        new_content = original_content.replace(expected_text, replacement_text)

        try:
            new_content_bytes = new_content.encode("utf-8")
        except UnicodeEncodeError as e:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"Replacement text encoding error: {e}",
            )

        temp_file = None
        try:
            fd, temp_path_str = tempfile.mkstemp(
                dir=str(target_path.parent), text=False
            )
            temp_file = Path(temp_path_str)
            with os.fdopen(fd, "wb") as f:
                f.write(new_content_bytes)
                f.flush()
                os.fsync(f.fileno())

            # Attempt to preserve mode
            try:
                stat = target_path.stat()
                temp_file.chmod(stat.st_mode)
            except Exception:
                pass

            os.replace(temp_file, target_path)

            return ToolResult(
                call_id=call.call_id,
                success=True,
                output={
                    "operation": "edit",
                    "path": str(
                        target_path.relative_to(context.workspace_root).as_posix()
                    ),
                    "occurrences_replaced": actual_count,
                    "bytes_before": len(original_content.encode("utf-8")),
                    "bytes_after": len(new_content_bytes),
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
                error=f"Filesystem error during edit: {e}",
            )
