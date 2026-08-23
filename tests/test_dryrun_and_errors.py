"""Dry-run paths and error branches for extra coverage and safety proof."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import archive, backup, checksum, duplicate
from core.base import Action, OperationResult
from core.cli_helpers import print_result
from utils.config import Config
from utils.exceptions import OperationError, PathValidationError
from utils.security import resolve_path, validate_path


def test_config_load_classmethod(tmp_path: Path) -> None:
    cfg = Config.load(None)
    assert cfg.get("general.recursive") is True
    assert isinstance(cfg.data, dict)
    assert cfg.section("hashing")["algorithm"] == "sha256"


def test_resolve_path_error_on_null_byte() -> None:
    with pytest.raises(PathValidationError):
        resolve_path("bad\x00name", strict=True)


def test_validate_path_for_write_normal(tmp_path: Path) -> None:
    # A normal user path with for_write should be accepted.
    assert validate_path(tmp_path, must_exist=True, for_write=True) == tmp_path.resolve()


def test_hash_file_not_a_file(tmp_path: Path) -> None:
    with pytest.raises(OperationError):
        checksum.hash_file(tmp_path)  # a directory


def test_archive_dry_run_creates_nothing(tmp_path: Path) -> None:
    src = tmp_path / "s"
    src.mkdir()
    (src / "f.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "out.zip"
    result = archive.create_archive(src, out, dry_run=True)
    assert result.dry_run is True
    assert not out.exists()


def test_extract_dry_run(tmp_path: Path) -> None:
    src = tmp_path / "s"
    src.mkdir()
    (src / "f.txt").write_text("x", encoding="utf-8")
    arc = tmp_path / "a.zip"
    archive.create_archive(src, arc)
    out = tmp_path / "ex"
    result = archive.extract_archive(arc, out, dry_run=True)
    assert result.items >= 1
    assert not (out / "f.txt").exists()


def test_backup_dry_run(tmp_path: Path) -> None:
    src = tmp_path / "s"
    src.mkdir()
    (src / "f.txt").write_text("x", encoding="utf-8")
    dest = tmp_path / "b"
    result = backup.create_backup(src, dest, backup_type="full", dry_run=True)
    assert result.dry_run is True
    # No backup archive/dir should be created in dry-run.
    assert not any(dest.iterdir())


def test_restore_dry_run(tmp_path: Path) -> None:
    src = tmp_path / "s"
    src.mkdir()
    (src / "f.txt").write_text("payload", encoding="utf-8")
    dest = tmp_path / "b"
    result = backup.create_backup(src, dest, backup_type="full", compression=False, verify=False)
    name = result.extra["backup"]
    restored = tmp_path / "r"
    dr = backup.restore_backup(dest / name, restored, dry_run=True)
    assert dr.items >= 1
    assert not (restored / "f.txt").exists()


def test_duplicate_report_is_non_destructive(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("dup", encoding="utf-8")
    (tmp_path / "b.txt").write_text("dup", encoding="utf-8")
    duplicate.resolve_duplicates(tmp_path, action="report")
    # Both files still present after a report.
    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").exists()


def test_duplicate_unknown_action(tmp_path: Path) -> None:
    with pytest.raises(OperationError):
        duplicate.resolve_duplicates(tmp_path, action="nuke")


def test_print_result_with_errors_and_many_actions(capsys: pytest.CaptureFixture[str]) -> None:
    result = OperationResult(operation="demo")
    for i in range(30):
        result.add(Action(kind="move", source=f"file{i}", destination=f"dest{i}"))
    result.error("some error")
    result.finish()
    print_result(result, show_actions=5)  # exercises the "... and N more" branch
