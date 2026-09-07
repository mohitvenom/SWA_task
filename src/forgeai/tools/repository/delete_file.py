"""Tool for safely deleting a file from the workspace."""

import os

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


class DeleteFileTool(BaseTool):
    """Tool that deletes a file securely inside the workspace."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="delete_file",
            description=(
                "Delete a file safely within the workspace. "
                "Requires explicit confirmation. Does not delete directories."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file to delete.",
                    },
                    "confirmation": {
                        "type": "boolean",
                        "description": "Must be set to true to execute the deletion.",
                    },
                },
                "required": ["path", "confirmation"],
            },
            capability=ToolCapability.MUTATION,
            is_dangerous=True,
        )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        raw_path = call.arguments.get("path")
        confirmation = call.arguments.get("confirmation", False)

        if not raw_path or not isinstance(raw_path, str):
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Argument 'path' must be a non-empty string.",
            )
        if confirmation is not True:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Explicit confirmation=true is required to delete.",
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

        if target_path.is_dir():
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"Cannot delete directory: {raw_path}",
            )

        try:
            os.remove(target_path)
            return ToolResult(
                call_id=call.call_id,
                success=True,
                output={
                    "operation": "delete",
                    "path": str(
                        target_path.relative_to(context.workspace_root).as_posix()
                    ),
                    "deleted": True,
                },
            )
        except Exception as e:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"Filesystem error during delete: {e}",
            )
