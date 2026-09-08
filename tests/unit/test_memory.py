"""Unit tests for MemoryStore and MemoryContextBuilder."""

import json
from pathlib import Path
import pytest

from forgeai.memory.store import SQLiteMemoryStore
from forgeai.memory.models import ExecutionRecord, ExecutionEvent, MemoryContext, MemoryEntry, MemoryScope, MemoryCategory, MemoryProvenance
from forgeai.memory.builder import MemoryContextBuilder
from forgeai.config.settings import settings


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "memory.db"


@pytest.fixture
def memory_store(temp_db_path: Path) -> SQLiteMemoryStore:
    settings.memory_enabled = True
    settings.memory_db_path = str(temp_db_path)
    return SQLiteMemoryStore(db_path=temp_db_path)


def test_memory_store_initialization(memory_store: SQLiteMemoryStore, temp_db_path: Path) -> None:
    assert temp_db_path.exists()


def test_memory_store_record_lifecycle(memory_store: SQLiteMemoryStore) -> None:
    record = ExecutionRecord(
        repository_identifier="repo-1",
        repository_revision="abc1234",
        task_id="task-1",
        task_summary="Test objective"
    )
    memory_store.save_execution(record)

    # Check persistence
    records = memory_store.get_history("repo-1", limit=10)
    assert len(records) == 1
    assert records[0].execution_id == record.execution_id
    assert records[0].task_summary == "Test objective"

    event = ExecutionEvent(
        execution_id=record.execution_id,
        phase="PLANNING",
        event_type="SUCCESS",
        summary="Plan generated successfully"
    )
    memory_store.save_event(event)

    events = memory_store.get_events(record.execution_id)
    assert len(events) == 1
    assert events[0].phase == "PLANNING"


def test_memory_store_secret_redaction(memory_store: SQLiteMemoryStore) -> None:
    record = ExecutionRecord(
        repository_identifier="repo-1",
        repository_revision="abc1234",
        task_id="task-2",
        task_summary="Use password=secret123 and token=ghp_abcde"
    )
    memory_store.save_execution(record)
    
    event = ExecutionEvent(
        execution_id=record.execution_id,
        phase="CODING",
        event_type="ERROR",
        summary="Failed with API_KEY=supersecret"
    )
    memory_store.save_event(event)
    
    records = memory_store.get_history("repo-1", limit=10)
    assert "secret123" not in str(records[0].task_summary)
    assert "ghp_abcde" not in str(records[0].task_summary)
    
    events = memory_store.get_events(record.execution_id)
    assert "supersecret" not in events[0].summary


def test_memory_store_failure_isolation() -> None:
    # Use mock to force SQLite failure to test graceful degradation
    from unittest import mock
    import sqlite3
    settings.memory_enabled = True
    settings.memory_db_path = "/tmp/memory.db"
    
    with mock.patch("sqlite3.connect", side_effect=sqlite3.OperationalError("Mock SQLite Error")):
        store = SQLiteMemoryStore(db_path=Path(settings.memory_db_path))
        
        record = ExecutionRecord(
            repository_identifier="repo-1",
            repository_revision="abc1234",
            task_id="task-3",
            task_summary="Test objective"
        )
        # This should not raise an exception
        store.save_execution(record)
        
        event = ExecutionEvent(
            execution_id=record.execution_id,
            phase="PLANNING",
            event_type="SUCCESS",
            summary="Success"
        )
        # This should not raise an exception
        store.save_event(event)
        
        # Retrieving should return empty, not crash
        assert store.get_history("repo-1") == []


def test_memory_context_builder(memory_store: SQLiteMemoryStore) -> None:
    record = ExecutionRecord(
        repository_identifier="repo-1",
        repository_revision="abc1234",
        task_id="task-4",
        task_summary="Fix memory leak"
    )
    memory_store.save_execution(record)
    
    entry = MemoryEntry(
        scope=MemoryScope.TASK,
        repository_identifier="repo-1",
        task_id="task-4",
        category=MemoryCategory.FAILURE,
        content="Docker timeout",
        source=MemoryProvenance.SYSTEM
    )
    memory_store.save_entry(entry)
    
    builder = MemoryContextBuilder(memory_store)
    context = builder.build_context("repo-1", "task-4")
    
    assert context is not None
    assert len(context.historical_executions) == 1
    assert len(context.relevant_failures) == 1
    assert context.relevant_failures[0].category == MemoryCategory.FAILURE


def test_memory_context_builder_disabled(memory_store: SQLiteMemoryStore) -> None:
    settings.memory_enabled = False
    builder = MemoryContextBuilder(memory_store)
    context = builder.build_context("repo-1", "task-4")
    assert context is None
