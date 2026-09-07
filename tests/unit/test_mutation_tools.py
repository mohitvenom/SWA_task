"""Unit tests for mutation tools (Write, Edit, Delete)."""

from pathlib import Path

import pytest

from forgeai.tools.errors import SecurityViolationError
from forgeai.tools.models import ToolCall, ToolContext
from forgeai.tools.repository.delete_file import DeleteFileTool
from forgeai.tools.repository.edit_file import EditFileTool
from forgeai.tools.repository.write_file import WriteFileTool


@pytest.fixture
def context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path)


# ==============================================================================
# WriteFileTool Tests
# ==============================================================================


@pytest.mark.anyio
async def test_write_file_new(context: ToolContext, tmp_path: Path) -> None:
    tool = WriteFileTool()
    call = ToolCall(
        call_id="1",
        name="write_file",
        arguments={"path": "new_folder/test.txt", "content": "Hello World"},
    )
    result = await tool.execute(call, context)

    assert result.success is True
    assert result.output["operation"] == "write"
    assert result.output["created"] is True

    target = tmp_path / "new_folder" / "test.txt"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "Hello World"


@pytest.mark.anyio
async def test_write_file_exists_no_overwrite(
    context: ToolContext, tmp_path: Path
) -> None:
    tool = WriteFileTool()
    target = tmp_path / "test.txt"
    target.write_text("old content")

    call = ToolCall(
        call_id="1",
        name="write_file",
        arguments={"path": "test.txt", "content": "new content", "overwrite": False},
    )
    result = await tool.execute(call, context)

    assert result.success is False
    assert "already exists" in result.error
    assert target.read_text() == "old content"


@pytest.mark.anyio
async def test_write_file_exists_overwrite(
    context: ToolContext, tmp_path: Path
) -> None:
    tool = WriteFileTool()
    target = tmp_path / "test.txt"
    target.write_text("old content")

    call = ToolCall(
        call_id="1",
        name="write_file",
        arguments={"path": "test.txt", "content": "new content", "overwrite": True},
    )
    result = await tool.execute(call, context)

    assert result.success is True
    assert result.output["overwritten"] is True
    assert target.read_text() == "new content"


@pytest.mark.anyio
async def test_write_file_path_traversal(context: ToolContext) -> None:
    tool = WriteFileTool()
    call = ToolCall(
        call_id="1",
        name="write_file",
        arguments={"path": "../outside.txt", "content": "hack"},
    )
    with pytest.raises(SecurityViolationError):
        await tool.execute(call, context)


# ==============================================================================
# EditFileTool Tests
# ==============================================================================


@pytest.mark.anyio
async def test_edit_file_success(context: ToolContext, tmp_path: Path) -> None:
    tool = EditFileTool()
    target = tmp_path / "test.py"
    target.write_text("def foo():\n    return 1\n", encoding="utf-8")

    call = ToolCall(
        call_id="1",
        name="edit_file",
        arguments={
            "path": "test.py",
            "expected_text": "return 1",
            "replacement_text": "return 2",
            "expected_count": 1,
        },
    )
    result = await tool.execute(call, context)

    assert result.success is True
    assert result.output["operation"] == "edit"
    assert result.output["occurrences_replaced"] == 1

    assert target.read_text(encoding="utf-8") == "def foo():\n    return 2\n"


@pytest.mark.anyio
async def test_edit_file_count_mismatch(context: ToolContext, tmp_path: Path) -> None:
    tool = EditFileTool()
    target = tmp_path / "test.py"
    target.write_text("return 1\nreturn 1\n", encoding="utf-8")

    call = ToolCall(
        call_id="1",
        name="edit_file",
        arguments={
            "path": "test.py",
            "expected_text": "return 1",
            "replacement_text": "return 2",
            "expected_count": 1,  # Should fail because there are 2
        },
    )
    result = await tool.execute(call, context)

    assert result.success is False
    assert "Occurrence mismatch" in result.error
    assert target.read_text(encoding="utf-8") == "return 1\nreturn 1\n"  # Untouched


@pytest.mark.anyio
async def test_edit_file_missing(context: ToolContext) -> None:
    tool = EditFileTool()
    call = ToolCall(
        call_id="1",
        name="edit_file",
        arguments={
            "path": "missing.txt",
            "expected_text": "foo",
            "replacement_text": "bar",
            "expected_count": 1,
        },
    )
    result = await tool.execute(call, context)
    assert result.success is False
    assert "File not found" in result.error


# ==============================================================================
# DeleteFileTool Tests
# ==============================================================================


@pytest.mark.anyio
async def test_delete_file_success(context: ToolContext, tmp_path: Path) -> None:
    tool = DeleteFileTool()
    target = tmp_path / "test.txt"
    target.write_text("to delete")

    call = ToolCall(
        call_id="1",
        name="delete_file",
        arguments={"path": "test.txt", "confirmation": True},
    )
    result = await tool.execute(call, context)

    assert result.success is True
    assert result.output["deleted"] is True
    assert not target.exists()


@pytest.mark.anyio
async def test_delete_file_no_confirmation(
    context: ToolContext, tmp_path: Path
) -> None:
    tool = DeleteFileTool()
    target = tmp_path / "test.txt"
    target.write_text("to delete")

    call = ToolCall(
        call_id="1",
        name="delete_file",
        arguments={"path": "test.txt"},  # Missing confirmation
    )
    result = await tool.execute(call, context)

    assert result.success is False
    assert "Explicit confirmation" in result.error
    assert target.exists()


@pytest.mark.anyio
async def test_delete_file_is_dir(context: ToolContext, tmp_path: Path) -> None:
    tool = DeleteFileTool()
    target = tmp_path / "my_dir"
    target.mkdir()

    call = ToolCall(
        call_id="1",
        name="delete_file",
        arguments={"path": "my_dir", "confirmation": True},
    )
    result = await tool.execute(call, context)

    assert result.success is False
    assert "Cannot delete directory" in result.error
    assert target.exists()


# ==============================================================================
# Integration Workflow Tests
# ==============================================================================


@pytest.mark.anyio
async def test_workflow_write_edit_delete(context: ToolContext, tmp_path: Path) -> None:
    writer = WriteFileTool()
    editor = EditFileTool()
    deleter = DeleteFileTool()

    # 1. Write
    call_write = ToolCall(
        call_id="1",
        name="write_file",
        arguments={"path": "wf.txt", "content": "base version\n"},
    )
    assert (await writer.execute(call_write, context)).success is True

    # 2. Edit
    call_edit = ToolCall(
        call_id="2",
        name="edit_file",
        arguments={
            "path": "wf.txt",
            "expected_text": "base",
            "replacement_text": "v2",
            "expected_count": 1,
        },
    )
    assert (await editor.execute(call_edit, context)).success is True
    assert (tmp_path / "wf.txt").read_text() == "v2 version\n"

    # 3. Delete
    call_del = ToolCall(
        call_id="3",
        name="delete_file",
        arguments={"path": "wf.txt", "confirmation": True},
    )
    assert (await deleter.execute(call_del, context)).success is True
    assert not (tmp_path / "wf.txt").exists()
