"""Small, cheap tests to cover remaining helper branches."""

from __future__ import annotations

import logging
from pathlib import Path

from core import scheduler
from utils import reporting
from utils.fs import ensure_directory, extension_of, file_info
from utils.logging_config import setup_logging
from utils.security import is_within, iter_files, unique_destination


def test_logging_with_console_handler(tmp_path: Path) -> None:
    logger = setup_logging(
        {"level": "INFO", "directory": "logs", "file": "c.log", "console": True}, root=tmp_path
    )
    # A console + file handler should both be attached.
    handler_types = {type(h).__name__ for h in logger.handlers}
    assert "RotatingFileHandler" in handler_types
    assert "StreamHandler" in handler_types
    logging.getLogger("aftk").handlers.clear()


def test_unique_destination_multiple_collisions(tmp_path: Path) -> None:
    base = tmp_path / "f.txt"
    base.write_text("0", encoding="utf-8")
    (tmp_path / "f (1).txt").write_text("1", encoding="utf-8")
    (tmp_path / "f (2).txt").write_text("2", encoding="utf-8")
    result = unique_destination(base)
    assert result.name == "f (3).txt"


def test_iter_files_single_file(tmp_path: Path) -> None:
    f = tmp_path / "solo.txt"
    f.write_text("x", encoding="utf-8")
    files = list(iter_files(f))
    assert files == [f.resolve()]


def test_is_within_unrelated(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert is_within(a, b) is False


def test_fs_helpers(tmp_path: Path) -> None:
    assert extension_of(Path("noext")) == ""
    d = ensure_directory(tmp_path / "made" / "deep")
    assert d.is_dir()
    f = tmp_path / "x.txt"
    f.write_text("hello", encoding="utf-8")
    info = file_info(f)
    assert info.size == 5
    assert info.category == "Documents"


def test_reporting_csv_summary_fallback() -> None:
    # No 'rows' -> CSV renders the summary as key/value pairs.
    payload = {"summary": {"items": 3, "bytes": 99}}
    csv_text = reporting.render(payload, "csv")
    assert "key,value" in csv_text
    assert "items,3" in csv_text


def test_reporting_summarise_paths() -> None:
    frag = reporting.summarise_paths([Path("a.txt"), Path("b.txt")])
    assert len(frag["rows"]) == 2


def test_scheduler_run_once_return_value() -> None:
    # run_once with a single job should execute and return None cleanly.
    ran = []
    scheduler.run_scheduler([scheduler.ScheduledJob("x", func=lambda: ran.append(1))], run_once=True)
    assert ran == [1]
