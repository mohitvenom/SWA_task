"""SQLite persistence for Task Memory and Execution History."""

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forgeai.memory.models import (
    ExecutionEvent,
    ExecutionRecord,
    MemoryCategory,
    MemoryEntry,
    MemoryProvenance,
    MemoryScope,
)

logger = logging.getLogger(__name__)


class MemoryStoreError(Exception):
    """Raised when memory persistence fails. Designed for graceful degradation."""
    pass


def _redact_secrets(text: str | None) -> str | None:
    """Deterministically redact common secrets and tokens from text."""
    if not text:
        return text
    # Very basic redaction as defense in depth
    patterns = [
        (r"(?i)(api[_-]?key[\s=:]+)([a-zA-Z0-9_\-]+)", r"\1***REDACTED***"),
        (r"(?i)(password[\s=:]+)([a-zA-Z0-9_\-]+)", r"\1***REDACTED***"),
        (r"(?i)(secret[\s=:]+)([a-zA-Z0-9_\-]+)", r"\1***REDACTED***"),
        (r"(?i)(token[\s=:]+)(glpat-[a-zA-Z0-9_\-]+|gh[pousr]_[a-zA-Z0-9_]+)", r"\1***REDACTED***"),
        (r"(?i)(sk-[a-zA-Z0-9_\-]+)", r"***REDACTED_SK***"),
    ]
    for pattern, repl in patterns:
        text = re.sub(pattern, repl, text)
    return text


class MemoryStore:
    """Abstract interface for memory persistence."""

    def save_execution(self, record: ExecutionRecord) -> None:
        raise NotImplementedError

    def get_execution(self, execution_id: str) -> ExecutionRecord | None:
        raise NotImplementedError

    def save_event(self, event: ExecutionEvent) -> None:
        raise NotImplementedError

    def get_events(self, execution_id: str) -> list[ExecutionEvent]:
        raise NotImplementedError

    def save_entry(self, entry: MemoryEntry) -> None:
        raise NotImplementedError

    def get_history(self, repository_identifier: str, limit: int = 10) -> list[ExecutionRecord]:
        raise NotImplementedError

    def get_entries(self, repository_identifier: str, limit: int = 50) -> list[MemoryEntry]:
        raise NotImplementedError


class SQLiteMemoryStore(MemoryStore):
    """SQLite implementation of the MemoryStore."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            isolation_level=None  # autocommit mode, handle transactions manually
        )
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute("BEGIN TRANSACTION;")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS execution_records (
                        execution_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        repository_identifier TEXT NOT NULL,
                        repository_revision TEXT,
                        started_at TEXT NOT NULL,
                        completed_at TEXT,
                        status TEXT NOT NULL,
                        task_summary TEXT,
                        outcome TEXT,
                        affected_files TEXT,
                        authorized_files TEXT,
                        validation_summary TEXT,
                        review_summary TEXT,
                        repair_summary TEXT,
                        failure_summary TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS execution_events (
                        event_id TEXT PRIMARY KEY,
                        execution_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        phase TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        metadata TEXT,
                        FOREIGN KEY(execution_id) REFERENCES execution_records(execution_id)
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memory_entries (
                        memory_id TEXT PRIMARY KEY,
                        scope TEXT NOT NULL,
                        repository_identifier TEXT NOT NULL,
                        task_id TEXT,
                        category TEXT NOT NULL,
                        content TEXT NOT NULL,
                        source TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        expires_at TEXT,
                        execution_id TEXT
                    )
                """)
                conn.execute("COMMIT;")
        except Exception as e:
            logger.error(f"Failed to initialize memory DB: {e}")

    def save_execution(self, record: ExecutionRecord) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute("BEGIN TRANSACTION;")
                conn.execute("""
                    INSERT INTO execution_records (
                        execution_id, task_id, repository_identifier, repository_revision,
                        started_at, completed_at, status, task_summary, outcome,
                        affected_files, authorized_files, validation_summary, review_summary,
                        repair_summary, failure_summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(execution_id) DO UPDATE SET
                        completed_at=excluded.completed_at,
                        status=excluded.status,
                        task_summary=excluded.task_summary,
                        outcome=excluded.outcome,
                        affected_files=excluded.affected_files,
                        authorized_files=excluded.authorized_files,
                        validation_summary=excluded.validation_summary,
                        review_summary=excluded.review_summary,
                        repair_summary=excluded.repair_summary,
                        failure_summary=excluded.failure_summary
                """, (
                    record.execution_id,
                    record.task_id,
                    record.repository_identifier,
                    record.repository_revision,
                    record.started_at.isoformat(),
                    record.completed_at.isoformat() if record.completed_at else None,
                    record.status,
                    _redact_secrets(record.task_summary),
                    _redact_secrets(record.outcome),
                    json.dumps(record.affected_files),
                    json.dumps(record.authorized_files),
                    _redact_secrets(record.validation_summary),
                    _redact_secrets(record.review_summary),
                    _redact_secrets(record.repair_summary),
                    _redact_secrets(record.failure_summary)
                ))
                conn.execute("COMMIT;")
        except Exception as e:
            logger.warning(f"Graceful degradation: Failed to save execution {record.execution_id}: {e}")
            # Do NOT raise here, isolate failure

    def get_execution(self, execution_id: str) -> ExecutionRecord | None:
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM execution_records WHERE execution_id = ?",
                    (execution_id,)
                ).fetchone()
                if not row:
                    return None
                return ExecutionRecord(
                    execution_id=row["execution_id"],
                    task_id=row["task_id"],
                    repository_identifier=row["repository_identifier"],
                    repository_revision=row["repository_revision"],
                    started_at=datetime.fromisoformat(row["started_at"]),
                    completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                    status=row["status"],
                    task_summary=row["task_summary"],
                    outcome=row["outcome"],
                    affected_files=json.loads(row["affected_files"] or "[]"),
                    authorized_files=json.loads(row["authorized_files"] or "[]"),
                    validation_summary=row["validation_summary"],
                    review_summary=row["review_summary"],
                    repair_summary=row["repair_summary"],
                    failure_summary=row["failure_summary"]
                )
        except Exception as e:
            logger.warning(f"Graceful degradation: Failed to get execution {execution_id}: {e}")
            return None

    def save_event(self, event: ExecutionEvent) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute("BEGIN TRANSACTION;")
                conn.execute("""
                    INSERT OR IGNORE INTO execution_events (
                        event_id, execution_id, timestamp, event_type, phase, summary, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id,
                    event.execution_id,
                    event.timestamp.isoformat(),
                    event.event_type,
                    event.phase,
                    _redact_secrets(event.summary),
                    _redact_secrets(json.dumps(event.metadata)) if event.metadata else "{}"
                ))
                conn.execute("COMMIT;")
        except Exception as e:
            logger.warning(f"Graceful degradation: Failed to save event {event.event_id}: {e}")

    def get_events(self, execution_id: str) -> list[ExecutionEvent]:
        try:
            events = []
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM execution_events WHERE execution_id = ? ORDER BY timestamp ASC",
                    (execution_id,)
                ).fetchall()
                for row in rows:
                    events.append(ExecutionEvent(
                        event_id=row["event_id"],
                        execution_id=row["execution_id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        event_type=row["event_type"],
                        phase=row["phase"],
                        summary=row["summary"],
                        metadata=json.loads(row["metadata"] or "{}")
                    ))
            return events
        except Exception as e:
            logger.warning(f"Graceful degradation: Failed to get events for {execution_id}: {e}")
            return []

    def save_entry(self, entry: MemoryEntry) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute("BEGIN TRANSACTION;")
                conn.execute("""
                    INSERT OR REPLACE INTO memory_entries (
                        memory_id, scope, repository_identifier, task_id, category, content,
                        source, confidence, created_at, updated_at, expires_at, execution_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry.memory_id,
                    entry.scope.value,
                    entry.repository_identifier,
                    entry.task_id,
                    entry.category.value,
                    _redact_secrets(entry.content) or "",
                    entry.source.value,
                    entry.confidence,
                    entry.created_at.isoformat(),
                    entry.updated_at.isoformat(),
                    entry.expires_at.isoformat() if entry.expires_at else None,
                    entry.execution_id
                ))
                conn.execute("COMMIT;")
        except Exception as e:
            logger.warning(f"Graceful degradation: Failed to save memory entry {entry.memory_id}: {e}")

    def get_history(self, repository_identifier: str, limit: int = 10) -> list[ExecutionRecord]:
        try:
            records = []
            with self._get_connection() as conn:
                rows = conn.execute(
                    """SELECT * FROM execution_records 
                       WHERE repository_identifier = ? 
                       ORDER BY started_at DESC LIMIT ?""",
                    (repository_identifier, limit)
                ).fetchall()
                for row in rows:
                    records.append(ExecutionRecord(
                        execution_id=row["execution_id"],
                        task_id=row["task_id"],
                        repository_identifier=row["repository_identifier"],
                        repository_revision=row["repository_revision"],
                        started_at=datetime.fromisoformat(row["started_at"]),
                        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                        status=row["status"],
                        task_summary=row["task_summary"],
                        outcome=row["outcome"],
                        affected_files=json.loads(row["affected_files"] or "[]"),
                        authorized_files=json.loads(row["authorized_files"] or "[]"),
                        validation_summary=row["validation_summary"],
                        review_summary=row["review_summary"],
                        repair_summary=row["repair_summary"],
                        failure_summary=row["failure_summary"]
                    ))
            return records
        except Exception as e:
            logger.warning(f"Graceful degradation: Failed to get history for {repository_identifier}: {e}")
            return []

    def get_entries(self, repository_identifier: str, limit: int = 50) -> list[MemoryEntry]:
        try:
            entries = []
            with self._get_connection() as conn:
                rows = conn.execute(
                    """SELECT * FROM memory_entries 
                       WHERE repository_identifier = ? 
                       ORDER BY created_at DESC LIMIT ?""",
                    (repository_identifier, limit)
                ).fetchall()
                for row in rows:
                    entries.append(MemoryEntry(
                        memory_id=row["memory_id"],
                        scope=MemoryScope(row["scope"]),
                        repository_identifier=row["repository_identifier"],
                        task_id=row["task_id"],
                        category=MemoryCategory(row["category"]),
                        content=row["content"],
                        source=MemoryProvenance(row["source"]),
                        confidence=row["confidence"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                        expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
                        execution_id=row["execution_id"]
                    ))
            return entries
        except Exception as e:
            logger.warning(f"Graceful degradation: Failed to get entries for {repository_identifier}: {e}")
            return []
