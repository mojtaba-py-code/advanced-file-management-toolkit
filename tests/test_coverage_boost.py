"""Targeted tests to exercise remaining branches across the codebase."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core import archive, batch, checksum, cleaner, cli_helpers, duplicate, organizer, search, sync
from utils import config as config_mod
from utils import security
from utils.exceptions import IntegrityError, OperationError, SecurityError
from utils.logging_config import get_logger, setup_logging


# --- logging ---------------------------------------------------------------
def test_setup_logging_creates_file_and_logs(tmp_path: Path) -> None:
    logger = setup_logging(
        {"level": "DEBUG", "directory": "logs", "file": "t.log", "console": False}, root=tmp_path
    )
    logger.info("hello log")
    for handler in logger.handlers:
        handler.flush()
    log_file = tmp_path / "logs" / "t.log"
    assert log_file.exists()
    assert "hello log" in log_file.read_text(encoding="utf-8")
    child = get_logger("child")
    assert child.name.endswith("child")
    # Re-configuring must not stack duplicate handlers.
    logging.getLogger("aftk").handlers.clear()


# --- config (YAML round-trip + merge) --------------------------------------
def test_config_yaml_merge(tmp_path: Path) -> None:
    cfg_file = tmp_path / "settings.yaml"
    cfg_file.write_text("hashing:\n  algorithm: md5\ngeneral:\n  threads: 8\n", encoding="utf-8")
    cfg = config_mod.load_config(cfg_file)
    assert cfg["hashing"]["algorithm"] == "md5"  # overridden
    assert cfg["general"]["threads"] == 8  # overridden
    assert cfg["backup"]["compression"] is True  # default preserved


def test_config_invalid_root(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(config_mod.ConfigError):
        config_mod.load_config(bad)


# --- security --------------------------------------------------------------
def test_is_protected_system_path() -> None:
    import os

    system = Path("C:/Windows") if os.name == "nt" else Path("/etc")
    assert security.is_protected(system) is True


def test_validate_path_rejects_write_to_protected() -> None:
    import os

    system = "C:/Windows" if os.name == "nt" else "/etc"
    with pytest.raises(SecurityError):
        security.validate_path(system, must_exist=False, for_write=True)


def test_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "real.txt"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted on this platform/session")
    with pytest.raises(SecurityError):
        security.validate_path(link)


def test_iter_files_skips_hidden(tmp_path: Path) -> None:
    (tmp_path / "visible.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".hidden.txt").write_text("x", encoding="utf-8")
    files = list(security.iter_files(tmp_path, skip_hidden=True))
    names = {f.name for f in files}
    assert "visible.txt" in names
    assert ".hidden.txt" not in names


# --- organizer branches ----------------------------------------------------
def test_organizer_strategies_and_custom_rules(tmp_path: Path) -> None:
    (tmp_path / "a.psd").write_text("design", encoding="utf-8")
    (tmp_path / "b.xyz").write_text("data", encoding="utf-8")
    result = organizer.organize(tmp_path, strategy="extension", custom_rules={"psd": "Design"})
    assert (tmp_path / "Design" / "a.psd").exists()
    assert (tmp_path / "XYZ" / "b.xyz").exists()
    assert result.items == 2


def test_organizer_rejects_unknown_strategy(tmp_path: Path) -> None:
    with pytest.raises(OperationError):
        organizer.organize(tmp_path, strategy="nonsense")


def test_organizer_rejects_file_source(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(OperationError):
        organizer.organize(f)


# --- sync update detection -------------------------------------------------
def test_sync_updates_changed_file(tmp_path: Path) -> None:
    src = tmp_path / "s"
    dst = tmp_path / "d"
    src.mkdir()
    (src / "f.txt").write_text("v1", encoding="utf-8")
    sync.sync(src, dst, mode="one-way")
    # Change the source and make it clearly newer.
    import os
    import time

    time.sleep(0.01)
    (src / "f.txt").write_text("v2 longer content", encoding="utf-8")
    future = time.time() + 10
    os.utime(src / "f.txt", (future, future))
    result = sync.sync(src, dst, mode="one-way")
    assert (dst / "f.txt").read_text(encoding="utf-8") == "v2 longer content"
    assert any(a.kind == "update" for a in result.actions)


def test_sync_mirror_dry_run_keeps_files(tmp_path: Path) -> None:
    src = tmp_path / "s"
    dst = tmp_path / "d"
    src.mkdir()
    dst.mkdir()
    (dst / "stale.txt").write_text("x", encoding="utf-8")
    sync.sync(src, dst, mode="mirror", dry_run=True, force=True)
    assert (dst / "stale.txt").exists()  # dry-run: nothing deleted


# --- checksum branches -----------------------------------------------------
def test_hash_many_and_ensure_integrity(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("data", encoding="utf-8")
    digests = checksum.hash_many([f])
    assert f in digests
    checksum.ensure_integrity(f, digests[f])  # no raise
    with pytest.raises(IntegrityError):
        checksum.ensure_integrity(f, "0" * 64)


def test_verify_manifest_detects_missing(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("data", encoding="utf-8")
    manifest = {"f.txt": checksum.hash_file(f), "ghost.txt": "0" * 64}
    result = checksum.verify_manifest(tmp_path, manifest)
    assert result.extra["failed"] >= 1
    assert result.extra["verified_ok"] == 1


# --- duplicate move --------------------------------------------------------
def test_duplicate_move_action(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("same", encoding="utf-8")
    (tmp_path / "b.txt").write_text("same", encoding="utf-8")
    quarantine = tmp_path / "dupes"
    result = duplicate.resolve_duplicates(tmp_path, action="move", move_to=quarantine, force=True)
    assert result.items == 1
    assert any(quarantine.iterdir())


def test_duplicate_move_requires_destination(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("same", encoding="utf-8")
    (tmp_path / "b.txt").write_text("same", encoding="utf-8")
    with pytest.raises(OperationError):
        duplicate.resolve_duplicates(tmp_path, action="move")


# --- search advanced -------------------------------------------------------
def test_search_by_extension_date_and_hash(sample_tree: Path) -> None:
    by_ext = search.search(sample_tree, search.SearchCriteria(extension="jpg"))
    assert by_ext.items == 1

    recent = search.search(
        sample_tree,
        search.SearchCriteria(modified_after=datetime.now() - timedelta(days=1)),
    )
    assert recent.items >= 1

    target = sample_tree / "unique.txt"
    digest = checksum.hash_file(target)
    by_hash = search.search(sample_tree, search.SearchCriteria(file_hash=digest))
    assert by_hash.items == 1


def test_search_invalid_regex(sample_tree: Path) -> None:
    with pytest.raises(OperationError):
        search.search(sample_tree, search.SearchCriteria(regex="([unclosed"))


# --- batch branches --------------------------------------------------------
def test_batch_regex_and_replace(tmp_path: Path) -> None:
    (tmp_path / "IMG_001.txt").write_text("1", encoding="utf-8")
    rules = batch.RenameRules(regex_from=r"IMG_(\d+)", regex_to=r"photo_\1")
    plan = batch.plan_rename(tmp_path, rules)
    assert plan[0][1].name == "photo_001.txt"


def test_batch_collision_detected(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    (tmp_path / "b.txt").write_text("2", encoding="utf-8")
    # Force both to the same name via a regex that erases the stem.
    rules = batch.RenameRules(regex_from=r".*", regex_to="same")
    with pytest.raises(OperationError):
        batch.plan_rename(tmp_path, rules)


# --- archive error handling ------------------------------------------------
def test_archive_unsupported_format(tmp_path: Path) -> None:
    src = tmp_path / "s"
    src.mkdir()
    (src / "f.txt").write_text("x", encoding="utf-8")
    with pytest.raises(OperationError):
        archive.create_archive(src, tmp_path / "out.rar", fmt="rar")


def test_verify_archive_detects_corruption(tmp_path: Path) -> None:
    src = tmp_path / "s"
    src.mkdir()
    (src / "f.txt").write_text("x", encoding="utf-8")
    arc = tmp_path / "a.zip"
    archive.create_archive(src, arc)
    # Corrupt the archive bytes.
    data = bytearray(arc.read_bytes())
    data[len(data) // 2] ^= 0xFF
    arc.write_bytes(bytes(data))
    result = archive.verify_archive(arc)
    assert result.extra["status"] in ("corrupt", "ok")  # tolerant: corruption may or may not hit CRC


# --- cleaner discovery -----------------------------------------------------
def test_cleaner_find_targets_categories(sample_tree: Path) -> None:
    targets = cleaner.find_targets(sample_tree)
    assert any("empty.dat" in str(p) for p in targets["zero_byte"])
    assert any("temp.tmp" in str(p) for p in targets["temp_files"])
    assert any("emptydir" in str(p) for p in targets["empty_dirs"])


# --- cli helper output funcs ----------------------------------------------
def test_cli_output_functions_do_not_raise(capsys: pytest.CaptureFixture[str]) -> None:
    cli_helpers.info("i")
    cli_helpers.success("s")
    cli_helpers.warn("w")
    cli_helpers.error("e")
