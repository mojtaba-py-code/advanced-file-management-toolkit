"""Tests for the SQLite history layer and the disk-usage analyzer."""

from __future__ import annotations

from pathlib import Path

from core import analyzer
from database.history import HistoryDB, OperationRecord


def test_history_record_and_recent(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    row_id = db.record(OperationRecord(operation="backup", status="ok", items=3, bytes=100))
    assert row_id > 0
    recent = db.recent(limit=5)
    assert len(recent) == 1
    assert recent[0].operation == "backup"
    assert recent[0].items == 3


def test_history_stats_and_clear(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.record(OperationRecord(operation="clean", status="ok", items=2, bytes=10))
    db.record(OperationRecord(operation="clean", status="ok", items=1, bytes=5))
    db.record(OperationRecord(operation="sync", status="ok", items=4, bytes=40))
    stats = db.stats()
    assert stats["total_operations"] == 3
    assert stats["by_operation"]["clean"] == 2
    assert stats["total_items"] == 7
    removed = db.clear()
    assert removed == 3
    assert db.stats()["total_operations"] == 0


def test_analyzer_reports_sizes(sample_tree: Path) -> None:
    result = analyzer.analyze(sample_tree, top=3)
    assert result.extra["file_count"] >= 7
    assert result.extra["total_bytes"] > 0
    # Category breakdown should include the categories we created.
    categories = result.extra["by_category"]
    assert "Documents" in categories or "Images" in categories
