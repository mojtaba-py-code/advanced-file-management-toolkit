"""End-to-end tests for the CLI entry point (main.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import main


def _make_files(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    (root / "b.txt").write_text("hello", encoding="utf-8")
    (root / "pic.jpg").write_text("img", encoding="utf-8")


def test_cli_no_command_prints_help() -> None:
    assert main.main([]) == 0


def test_cli_version_exits() -> None:
    with pytest.raises(SystemExit) as exc:
        main.main(["--version"])
    assert exc.value.code == 0


def test_cli_organize_dry_run(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _make_files(src)
    assert main.main(["organize", str(src), "--dry-run"]) == 0
    # Dry-run: nothing moved.
    assert (src / "a.txt").exists()


def test_cli_search(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _make_files(src)
    assert main.main(["search", str(src), "--name", "*.txt"]) == 0


def test_cli_duplicates_report(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _make_files(src)
    assert main.main(["duplicates", str(src), "--action", "report"]) == 0


def test_cli_schedule_run_once(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "junk.tmp").write_text("x", encoding="utf-8")
    assert main.main(["schedule", "clean", str(src), "--run-once"]) == 0
    assert not (src / "junk.tmp").exists()


def test_cli_history_stats(tmp_path: Path) -> None:
    assert main.main(["history", "--stats"]) == 0


def test_cli_error_on_missing_path_returns_2(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    # A ToolkitError (PathValidationError) maps to exit code 2.
    assert main.main(["organize", str(missing)]) == 2
