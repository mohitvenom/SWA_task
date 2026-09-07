"""Tool for reading file contents."""

from forgeai.tools.base import BaseTool
from forgeai.tools.models import (
    ToolCall,
    ToolCapability,
    ToolContext,
    ToolDefinition,
    ToolResult,
)
from forgeai.tools.repository.utils import resolve_safe_path


class ReadFileTool(BaseTool):
    """Tool that safely reads a file from the workspace."""

    MAX_BYTES = 50 * 1024  # 50KB

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description="Read the contents of a file in the workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional 1-indexed start line.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional 1-indexed end line.",
                    },
                },
                "required": ["path"],
            },
            capability=ToolCapability.READ_ONLY,
        )

    def _is_binary(self, bytes_data: bytes) -> bool:
        """Heuristic to check if a file is binary."""
        textchars = bytearray(
            {7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F}
        )
        if not bytes_data:
            return False
        return bool(bytes_data.translate(None, textchars))

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        path_str = call.arguments.get("path")
        if not path_str:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Missing required argument: path",
            )

        start_line = call.arguments.get("start_line")
        end_line = call.arguments.get("end_line")

        try:
            resolved_path = resolve_safe_path(context.workspace_root, path_str)
            if not resolved_path.is_file():
                return ToolResult(
                    call_id=call.call_id,
                    success=False,
                    error=f"File not found or is a directory: {path_str}",
                )

            # Read bounded chunk to check for binary/size
            with open(resolved_path, "rb") as f:
                chunk = f.read(1024)
                if self._is_binary(chunk):
                    return ToolResult(
                        call_id=call.call_id,
                        success=False,
                        error="Binary files are not supported.",
                    )

            # Read file safely
            with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)

            # 1-indexed
            s_idx = max(0, start_line - 1) if start_line else 0
            e_idx = min(total_lines, end_line) if end_line else total_lines

            if s_idx >= total_lines:
                return ToolResult(
                    call_id=call.call_id,
                    success=False,
                    error=(
                        f"Start line {start_line} is beyond file length "
                        f"({total_lines} lines)."
                    ),
                )

            selected_lines = lines[s_idx:e_idx]
            content = "".join(selected_lines)

            truncated = False
            if len(content.encode("utf-8")) > self.MAX_BYTES:
                content = content.encode("utf-8")[: self.MAX_BYTES].decode(
                    "utf-8", errors="replace"
                )
                truncated = True
                content += "\n\n...[Content Truncated due to size limit]..."

            return ToolResult(
                call_id=call.call_id,
                success=True,
                output={
                    "content": content,
                    "truncated": truncated,
                    "total_lines": total_lines,
                    "shown_lines": f"{s_idx + 1}-{s_idx + len(selected_lines)}",
                },
            )
        except Exception as e:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"Failed to read file: {e}",
            )
