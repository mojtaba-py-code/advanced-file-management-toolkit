"""Additional tests targeting scheduler, monitor, CLI helpers and edge cases."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from core import archive, backup, batch, cli_helpers, monitor, scheduler, search, sync
from core.base import Action, OperationResult
from database.history import HistoryDB


# --- base.OperationResult --------------------------------------------------
def test_operation_result_serialisation() -> None:
    result = OperationResult(operation="demo", dry_run=True)
    result.add(Action(kind="move", source="a", destination="b", size=10))
    result.error("boom")
    result.finish()
    payload = result.to_payload()
    assert payload["summary"]["items"] == 1
    assert payload["summary"]["bytes"] == 10
    assert payload["errors"] == ["boom"]
    assert payload["rows"][0]["action"] == "move"


# --- scheduler -------------------------------------------------------------
def test_scheduler_run_once_executes_jobs() -> None:
    calls: list[str] = []
    jobs = [
        scheduler.ScheduledJob(name="one", func=lambda: calls.append("one")),
        scheduler.ScheduledJob(name="two", func=lambda: calls.append("two")),
    ]
    scheduler.run_scheduler(jobs, run_once=True)
    assert calls == ["one", "two"]


def test_scheduler_run_once_survives_failing_job() -> None:
    calls: list[str] = []

    def boom() -> None:
        raise RuntimeError("fail")

    jobs = [
        scheduler.ScheduledJob(name="bad", func=boom),
        scheduler.ScheduledJob(name="good", func=lambda: calls.append("good")),
    ]
    scheduler.run_scheduler(jobs, run_once=True)  # must not raise
    assert calls == ["good"]


def test_scheduler_requires_jobs() -> None:
    from utils.exceptions import OperationError

    with pytest.raises(OperationError):
        scheduler.run_scheduler([], run_once=True)


# --- monitor (real watchdog events) ---------------------------------------
def test_monitor_detects_file_creation(tmp_path: Path) -> None:
    watched = tmp_path / "watched"
    watched.mkdir()
    seen: list[tuple[str, str]] = []

    def make_file() -> None:
        time.sleep(0.4)
        (watched / "created.txt").write_text("hello", encoding="utf-8")

    worker = threading.Thread(target=make_file)
    worker.start()
    count = monitor.monitor(watched, duration=1.2, callback=lambda kind, path: seen.append((kind, path)))
    worker.join()

    assert count >= 1
    assert any(kind in ("created", "modified") for kind, _ in seen)


# --- CLI helpers -----------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("1024", 1024),
        ("1KB", 1024),
        ("2K", 2048),
        ("1MB", 1024**2),
        ("1.5MB", int(1.5 * 1024**2)),
        ("1GB", 1024**3),
    ],
)
def test_parse_size(text: str, expected: int) -> None:
    assert cli_helpers.parse_size(text) == expected


def test_parse_date_valid_and_invalid() -> None:
    assert cli_helpers.parse_date("2026-01-15") == datetime(2026, 1, 15)
    with pytest.raises(ValueError):
        cli_helpers.parse_date("15/01/2026")


def test_print_result_and_history(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = OperationResult(operation="demo")
    result.add(Action(kind="copy", source="x", destination="y", size=5))
    result.finish()
    cli_helpers.print_result(result)
    # A report is written only when output is given.
    report = cli_helpers.maybe_report(result, str(tmp_path / "out"), "json")
    assert report is not None and report.exists()
    # History recording is best-effort and should not raise.
    db = HistoryDB(tmp_path / "h.db")
    cli_helpers.record_history(db, result, source="x")
    assert db.recent()[0].operation == "demo"


# --- extra branch coverage -------------------------------------------------
def test_sync_two_way_propagates_both_directions(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "only_a.txt").write_text("a", encoding="utf-8")
    (b / "only_b.txt").write_text("b", encoding="utf-8")
    sync.sync(a, b, mode="two-way")
    assert (b / "only_a.txt").exists()
    assert (a / "only_b.txt").exists()


def test_archive_tar_gz_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("data", encoding="utf-8")
    arc = tmp_path / "out.tar.gz"
    archive.create_archive(src, arc, fmt="tar.gz")
    assert arc.exists()
    out = tmp_path / "ex"
    archive.extract_archive(arc, out)
    assert (out / "f.txt").read_text(encoding="utf-8") == "data"


def test_backup_differential_and_list(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("one", encoding="utf-8")
    dest = tmp_path / "b"
    backup.create_backup(src, dest, backup_type="full", compression=False, verify=False)
    (src / "b.txt").write_text("two", encoding="utf-8")
    diff = backup.create_backup(src, dest, backup_type="differential", compression=False, verify=False)
    assert diff.items == 1  # only the new file
    listing = backup.list_backups(dest)
    assert len(listing) == 2


def test_search_by_size_and_regex(sample_tree: Path) -> None:
    by_regex = search.search(sample_tree, search.SearchCriteria(regex=r"^a\.txt$"))
    assert by_regex.items == 1
    by_size = search.search(sample_tree, search.SearchCriteria(min_size=1, max_size=100000))
    assert by_size.items >= 1


def test_batch_rename_case_and_number(tmp_path: Path) -> None:
    (tmp_path / "Alpha.txt").write_text("1", encoding="utf-8")
    (tmp_path / "Beta.txt").write_text("2", encoding="utf-8")
    rules = batch.RenameRules(case="lower", number=True, number_padding=2)
    plan = batch.plan_rename(tmp_path, rules)
    new_names = sorted(new.name for _old, new in plan)
    assert new_names == ["alpha_01.txt", "beta_02.txt"]
