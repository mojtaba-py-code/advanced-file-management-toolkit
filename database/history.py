"""Persistent operation history backed by SQLite.

Every meaningful action (organize, backup, delete, sync, ...) can be recorded
here so the toolkit keeps an auditable trail. The database is created lazily
and uses parameterised queries throughout — user-supplied strings are never
interpolated into SQL, eliminating injection risk.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    operation    TEXT    NOT NULL,
    source       TEXT,
    destination  TEXT,
    status       TEXT    NOT NULL,
    details      TEXT,
    items        INTEGER NOT NULL DEFAULT 0,
    bytes        INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_operations_ts ON operations(timestamp);
CREATE INDEX IF NOT EXISTS idx_operations_op ON operations(operation);
"""


@dataclass
class OperationRecord:
    """A single row in the operation history."""

    operation: str
    status: str
    source: str | None = None
    destination: str | None = None
    details: str | None = None
    items: int = 0
    bytes: int = 0
    duration_ms: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    id: int | None = None


class HistoryDB:
    """Thin, safe wrapper around the SQLite history database."""

    def __init__(self, db_path: str | Path = "database/history.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Enforce foreign keys and use WAL for better concurrency.
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialise(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def record(self, record: OperationRecord) -> int:
        """Persist *record* and return its new row id."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO operations
                    (timestamp, operation, source, destination, status,
                     details, items, bytes, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.operation,
                    record.source,
                    record.destination,
                    record.status,
                    record.details,
                    record.items,
                    record.bytes,
                    record.duration_ms,
                ),
            )
            return int(cursor.lastrowid or 0)

    def recent(self, limit: int = 20, *, operation: str | None = None) -> list[OperationRecord]:
        """Return the most recent records, optionally filtered by operation."""
        query = "SELECT * FROM operations"
        params: list[Any] = []
        if operation:
            query += " WHERE operation = ?"
            params.append(operation)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        """Return aggregate counters across all recorded operations."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM operations").fetchone()["c"]
            by_op = conn.execute(
                "SELECT operation, COUNT(*) AS c FROM operations GROUP BY operation"
            ).fetchall()
            totals = conn.execute(
                "SELECT COALESCE(SUM(items),0) AS items, COALESCE(SUM(bytes),0) AS bytes FROM operations"
            ).fetchone()
        return {
            "total_operations": total,
            "by_operation": {row["operation"]: row["c"] for row in by_op},
            "total_items": totals["items"],
            "total_bytes": totals["bytes"],
        }

    def clear(self) -> int:
        """Delete all history rows; returns the number of rows removed."""
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM operations").fetchone()["c"]
            conn.execute("DELETE FROM operations")
        return int(count)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> OperationRecord:
        return OperationRecord(
            id=row["id"],
            timestamp=row["timestamp"],
            operation=row["operation"],
            source=row["source"],
            destination=row["destination"],
            status=row["status"],
            details=row["details"],
            items=row["items"],
            bytes=row["bytes"],
            duration_ms=row["duration_ms"],
        )
