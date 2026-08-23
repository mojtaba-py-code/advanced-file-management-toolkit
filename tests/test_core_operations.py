"""Functional tests for the core feature modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import archive, backup, batch, checksum, cleaner, duplicate, organizer, search, sync
from utils.exceptions import OperationError, SecurityError


# --- checksum --------------------------------------------------------------
def test_hash_file_and_verify(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("hello", encoding="utf-8")
    digest = checksum.hash_file(f)
    assert len(digest) == 64  # sha256 hex
    assert checksum.verify_file(f, digest) is True
    assert checksum.verify_file(f, "0" * 64) is False


def test_hash_unknown_algorithm(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(OperationError):
        checksum.hash_file(f, algorithm="crc32")


def test_manifest_roundtrip(sample_tree: Path) -> None:
    result = checksum.generate_manifest(sample_tree)
    manifest = result.extra["manifest"]
    assert manifest  # non-empty
    verify = checksum.verify_manifest(sample_tree, manifest)
    assert verify.extra["failed"] == 0


# --- organizer -------------------------------------------------------------
def test_organize_by_category(sample_tree: Path) -> None:
    result = organizer.organize(sample_tree, strategy="category", dry_run=False)
    assert (sample_tree / "Images" / "photo.jpg").exists()
    assert (sample_tree / "Videos" / "clip.mp4").exists()
    assert (sample_tree / "Documents" / "a.txt").exists()
    assert result.items >= 5


def test_organize_dry_run_changes_nothing(sample_tree: Path) -> None:
    before = {p.name for p in sample_tree.iterdir()}
    organizer.organize(sample_tree, strategy="category", dry_run=True)
    after = {p.name for p in sample_tree.iterdir()}
    assert before == after


# --- duplicate -------------------------------------------------------------
def test_find_duplicates(sample_tree: Path) -> None:
    groups = duplicate.find_duplicates(sample_tree)
    # a.txt and b.txt share content.
    assert any(len(paths) == 2 for paths in groups.values())


def test_resolve_duplicates_delete(sample_tree: Path) -> None:
    result = duplicate.resolve_duplicates(sample_tree, action="delete", force=True)
    remaining = list(sample_tree.rglob("*.txt"))
    names = [p.name for p in remaining]
    # Exactly one of the duplicate pair should survive.
    assert ("a.txt" in names) ^ ("b.txt" in names)
    assert result.extra["reclaimable_bytes"] > 0


# --- sync ------------------------------------------------------------------
def test_sync_one_way(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "x.txt").write_text("data", encoding="utf-8")
    sync.sync(src, dst, mode="one-way")
    assert (dst / "x.txt").read_text(encoding="utf-8") == "data"


def test_sync_mirror_deletes_stale(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "keep.txt").write_text("keep", encoding="utf-8")
    (dst / "stale.txt").write_text("stale", encoding="utf-8")
    sync.sync(src, dst, mode="mirror", force=True)
    assert (dst / "keep.txt").exists()
    assert not (dst / "stale.txt").exists()


# --- archive (incl. zip-slip protection) -----------------------------------
def test_archive_roundtrip(sample_tree: Path, tmp_path: Path) -> None:
    arc = tmp_path / "out.zip"
    archive.create_archive(sample_tree, arc)
    assert arc.exists()
    verify = archive.verify_archive(arc)
    assert verify.extra["status"] == "ok"

    out = tmp_path / "extracted"
    archive.extract_archive(arc, out)
    assert (out / "a.txt").exists()


def test_extract_blocks_zip_slip(tmp_path: Path) -> None:
    import zipfile

    malicious = tmp_path / "evil.zip"
    with zipfile.ZipFile(malicious, "w") as zf:
        # A member that tries to escape the extraction directory.
        zf.writestr("../../escape.txt", "pwned")
    with pytest.raises(SecurityError):
        archive.extract_archive(malicious, tmp_path / "safe_out")


# --- backup ----------------------------------------------------------------
def test_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.txt").write_text("important", encoding="utf-8")
    (src / "sub").mkdir()
    (src / "sub" / "n.txt").write_text("nested", encoding="utf-8")

    dest = tmp_path / "backups"
    result = backup.create_backup(src, dest, backup_type="full", compression=True, verify=True)
    assert result.items == 2
    archive_name = result.extra["archive"]

    restored = tmp_path / "restored"
    backup.restore_backup(archive_name, restored)
    assert (restored / "doc.txt").read_text(encoding="utf-8") == "important"
    assert (restored / "sub" / "n.txt").read_text(encoding="utf-8") == "nested"


def test_incremental_backup_only_changes(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("one", encoding="utf-8")
    dest = tmp_path / "backups"
    backup.create_backup(src, dest, backup_type="full", compression=False, verify=False)

    # No change -> incremental backs up nothing.
    inc = backup.create_backup(src, dest, backup_type="incremental", compression=False, verify=False)
    assert inc.items == 0


# --- batch rename ----------------------------------------------------------
def test_batch_rename_prefix(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("1", encoding="utf-8")
    (tmp_path / "two.txt").write_text("2", encoding="utf-8")
    rules = batch.RenameRules(prefix="new_")
    batch.batch_rename(tmp_path, rules, dry_run=False)
    assert (tmp_path / "new_one.txt").exists()
    assert (tmp_path / "new_two.txt").exists()


def test_batch_rename_requires_rule(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("1", encoding="utf-8")
    with pytest.raises(OperationError):
        batch.batch_rename(tmp_path, batch.RenameRules())


# --- search ----------------------------------------------------------------
def test_search_by_name(sample_tree: Path) -> None:
    result = search.search(sample_tree, search.SearchCriteria(name="*.txt"))
    assert result.items >= 3


def test_search_by_content(sample_tree: Path) -> None:
    result = search.search(sample_tree, search.SearchCriteria(content="hello"))
    assert result.items == 2  # a.txt and b.txt


def test_search_requires_criterion(sample_tree: Path) -> None:
    with pytest.raises(OperationError):
        search.search(sample_tree, search.SearchCriteria())


# --- cleaner ---------------------------------------------------------------
def test_clean_removes_empty_and_temp(sample_tree: Path) -> None:
    result = cleaner.clean(sample_tree, force=True)
    assert not (sample_tree / "emptydir").exists()
    assert not (sample_tree / "empty.dat").exists()
    assert not (sample_tree / "temp.tmp").exists()
    # Real content files are untouched.
    assert (sample_tree / "unique.txt").exists()
    assert result.items >= 3
