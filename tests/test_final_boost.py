"""Final coverage pass: strategy variants and remaining branches."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from core import cli_helpers, organizer, scheduler, sync
from core.base import Action, OperationResult
from utils.exceptions import OperationError


def test_organizer_size_strategy(tmp_path: Path) -> None:
    small = tmp_path / "small.bin"
    small.write_bytes(b"x" * 10)
    medium = tmp_path / "medium.bin"
    medium.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB
    organizer.organize(tmp_path, strategy="size")
    assert (tmp_path / "Small (under 1MB)" / "small.bin").exists()
    assert (tmp_path / "Medium (1-100MB)" / "medium.bin").exists()


def test_organizer_date_strategies(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    for strategy in ("modified", "created"):
        # Fresh copy each time since organize moves the file.
        target = tmp_path / f"{strategy}.txt"
        target.write_text("x", encoding="utf-8")
        result = organizer.organize(tmp_path, strategy=strategy)
        assert result.items >= 1


def test_scheduler_rejects_invalid_unit() -> None:
    job = scheduler.ScheduledJob(name="bad", func=lambda: None, unit="weeks")
    with pytest.raises(OperationError):
        scheduler.run_scheduler([job], run_once=False)


def test_sync_two_way_newer_destination_wins(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "f.txt").write_text("old", encoding="utf-8")
    (b / "f.txt").write_text("new and longer", encoding="utf-8")
    # Make b's file clearly newer.
    future = time.time() + 100
    os.utime(b / "f.txt", (future, future))
    sync.sync(a, b, mode="two-way")
    assert (a / "f.txt").read_text(encoding="utf-8") == "new and longer"


def test_record_history_with_no_db_is_noop() -> None:
    result = OperationResult(operation="demo")
    result.add(Action(kind="x", source="s"))
    # Passing None must not raise.
    cli_helpers.record_history(None, result)


def test_maybe_report_without_output_returns_none() -> None:
    result = OperationResult(operation="demo").finish()
    assert cli_helpers.maybe_report(result, None, "json") is None
