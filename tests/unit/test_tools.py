"""Tests for the Tool System."""

import os
from pathlib import Path

import pytest

from forgeai.tools.base import BaseTool
from forgeai.tools.errors import (
    PathTraversalError,
    SecurityViolationError,
    ToolRegistrationError,
)
from forgeai.tools.models import ToolCall, ToolContext, ToolDefinition, ToolResult
from forgeai.tools.registry import ToolRegistry
from forgeai.tools.repository.list_files import ListFilesTool
from forgeai.tools.repository.read_file import ReadFileTool
from forgeai.tools.repository.search_code import SearchCodeTool
from forgeai.tools.repository.utils import resolve_safe_path


class DummyTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="dummy",
            description="A dummy tool.",
            input_schema={"type": "object", "properties": {}},
        )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        return ToolResult(call_id=call.call_id, success=True, output="dummy output")


def test_registry_registration() -> None:
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)

    assert len(registry.list_tools()) == 1
    assert registry.get("dummy") is tool

    with pytest.raises(ToolRegistrationError):
        registry.register(tool)

    with pytest.raises(ToolRegistrationError):
        registry.get("nonexistent")


def test_registry_schemas() -> None:
    registry = ToolRegistry()
    registry.register(DummyTool())

    schemas = registry.get_openai_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "dummy"
    assert schemas[0]["function"]["description"] == "A dummy tool."
    assert schemas[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_resolve_safe_path_success(tmp_path: Path) -> None:
    resolved = resolve_safe_path(tmp_path, "src/main.py")
    assert resolved == tmp_path / "src" / "main.py"

    # Absolute path that matches root
    resolved = resolve_safe_path(tmp_path, str(tmp_path / "src/main.py"))
    assert resolved == tmp_path / "src" / "main.py"


def test_resolve_safe_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        resolve_safe_path(tmp_path, "../outside.py")


def test_resolve_safe_path_absolute(tmp_path: Path) -> None:
    with pytest.raises(SecurityViolationError):
        # Path outside tmp_path
        if os.name == "nt":
            resolve_safe_path(tmp_path, "C:\\Windows\\System32\\cmd.exe")
        else:
            resolve_safe_path(tmp_path, "/etc/passwd")


def test_resolve_safe_path_sensitive(tmp_path: Path) -> None:
    with pytest.raises(SecurityViolationError):
        resolve_safe_path(tmp_path, ".env")

    with pytest.raises(SecurityViolationError):
        resolve_safe_path(tmp_path, "src/.env.production")


@pytest.fixture
def mock_workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello world')", encoding="utf-8")
    (tmp_path / "src" / "utils.py").write_text("def helper(): pass", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=123", encoding="utf-8")

    # Create ignored dir
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("ignored", encoding="utf-8")

    # Create binary file
    (tmp_path / "src" / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    return tmp_path


@pytest.mark.anyio
async def test_list_files_tool(mock_workspace: Path) -> None:
    tool = ListFilesTool()
    context = ToolContext(workspace_root=mock_workspace)
    call = ToolCall(call_id="1", name="list_files", arguments={})

    result = await tool.execute(call, context)
    assert result.success
    files = result.output["files"]

    assert "src/main.py" in files
    assert "src/utils.py" in files
    assert "src/image.png" in files
    # Check ignores
    assert ".env" not in files
    assert ".git/config" not in files


@pytest.mark.anyio
async def test_read_file_tool(mock_workspace: Path) -> None:
    tool = ReadFileTool()
    context = ToolContext(workspace_root=mock_workspace)

    # Successful read
    call = ToolCall(call_id="1", name="read_file", arguments={"path": "src/main.py"})
    result = await tool.execute(call, context)
    assert result.success
    assert "print('hello world')" in result.output["content"]
    assert result.output["total_lines"] == 1

    # Binary read (should fail)
    call = ToolCall(call_id="2", name="read_file", arguments={"path": "src/image.png"})
    result = await tool.execute(call, context)
    assert not result.success
    assert "Binary files are not supported" in result.error

    # Missing file
    call = ToolCall(call_id="3", name="read_file", arguments={"path": "missing.py"})
    result = await tool.execute(call, context)
    assert not result.success
    assert "File not found" in result.error


@pytest.mark.anyio
async def test_search_code_tool(mock_workspace: Path) -> None:
    tool = SearchCodeTool()
    context = ToolContext(workspace_root=mock_workspace)

    call = ToolCall(call_id="1", name="search_code", arguments={"query": "hello"})
    result = await tool.execute(call, context)
    assert result.success

    results = result.output["results"]
    assert len(results) == 1
    assert results[0]["path"] == "src/main.py"
    assert "print('hello world')" in results[0]["content"]
