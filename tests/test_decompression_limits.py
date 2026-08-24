"""Tests for the decompression-bomb limits on archive extraction.

Two independent limits are covered: a gate on the sizes an archive declares,
which refuses an obvious bomb before anything is written, and a running total of
bytes actually written, which catches the cumulative case.

The gate is only sound because zipfile and tarfile stop reading a member at its
declared length -- a member cannot quietly deliver more than it claims. That
assumption is load-bearing, so it is pinned down by a test of its own rather
than left implicit.
"""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest

from core.archive import (
    DEFAULT_MAX_COMPRESSION_RATIO,
    DEFAULT_MAX_EXTRACT_BYTES,
    extract_archive,
    verify_archive,
)
from utils.exceptions import OperationError, SecurityError

# Highly compressible payload: ~1 MiB of zeros shrinks to about a kilobyte.
BOMB_PAYLOAD = b"\0" * (1024 * 1024)


def _zip_with(tmp_path: Path, name: str, members: dict[str, bytes]) -> Path:
    archive = tmp_path / name
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for member_name, data in members.items():
            zf.writestr(member_name, data)
    return archive


def _tar_with(tmp_path: Path, name: str, members: dict[str, bytes]) -> Path:
    archive = tmp_path / name
    staging = tmp_path / "_staging"
    staging.mkdir(exist_ok=True)
    with tarfile.open(archive, "w:gz") as tf:
        for member_name, data in members.items():
            item = staging / member_name
            item.write_bytes(data)
            tf.add(item, arcname=member_name)
    return archive


# ---------------------------------------------------------------------------
# Defaults are sane — ordinary archives must keep working
# ---------------------------------------------------------------------------
def test_defaults_are_generous_enough_for_a_normal_archive(tmp_path: Path) -> None:
    archive = _zip_with(tmp_path, "normal.zip", {"a.txt": b"hello", "b.txt": b"world"})
    result = extract_archive(archive, tmp_path / "out")
    assert result.items == 2
    assert (tmp_path / "out" / "a.txt").read_bytes() == b"hello"
    assert (tmp_path / "out" / "b.txt").read_bytes() == b"world"


def test_default_limits_are_documented_values() -> None:
    assert DEFAULT_MAX_EXTRACT_BYTES == 2 * 1024**3
    assert DEFAULT_MAX_COMPRESSION_RATIO == 200


def test_nested_directories_still_extract(tmp_path: Path) -> None:
    archive = _zip_with(tmp_path, "nested.zip", {"deep/inner/file.txt": b"data"})
    extract_archive(archive, tmp_path / "out")
    assert (tmp_path / "out" / "deep" / "inner" / "file.txt").read_bytes() == b"data"


# ---------------------------------------------------------------------------
# The total-size ceiling
# ---------------------------------------------------------------------------
def test_zip_exceeding_the_byte_ceiling_is_refused(tmp_path: Path) -> None:
    archive = _zip_with(tmp_path, "bomb.zip", {"big.bin": BOMB_PAYLOAD})
    with pytest.raises(SecurityError, match="limit"):
        extract_archive(archive, tmp_path / "out", max_bytes=1024, max_ratio=None)


def test_tar_exceeding_the_byte_ceiling_is_refused(tmp_path: Path) -> None:
    archive = _tar_with(tmp_path, "bomb.tar.gz", {"big.bin": BOMB_PAYLOAD})
    with pytest.raises(SecurityError, match="limit"):
        extract_archive(archive, tmp_path / "out", max_bytes=1024, max_ratio=None)


def test_the_ceiling_is_cumulative_across_members(tmp_path: Path) -> None:
    """Many small members must not slip past a limit applied per member."""
    members = {f"f{i}.bin": b"x" * 400 for i in range(10)}
    archive = _zip_with(tmp_path, "many.zip", members)
    with pytest.raises(SecurityError):
        extract_archive(archive, tmp_path / "out", max_bytes=1000, max_ratio=None)


def test_a_lifted_ceiling_allows_the_same_archive(tmp_path: Path) -> None:
    archive = _zip_with(tmp_path, "big.zip", {"big.bin": BOMB_PAYLOAD})
    result = extract_archive(archive, tmp_path / "out", max_bytes=None, max_ratio=None)
    assert result.items == 1
    assert (tmp_path / "out" / "big.bin").stat().st_size == len(BOMB_PAYLOAD)


# ---------------------------------------------------------------------------
# The compression-ratio gate
# ---------------------------------------------------------------------------
def test_an_absurd_expansion_ratio_is_refused(tmp_path: Path) -> None:
    archive = _zip_with(tmp_path, "ratio.zip", {"big.bin": BOMB_PAYLOAD})
    with pytest.raises(SecurityError, match="ratio"):
        extract_archive(archive, tmp_path / "out", max_bytes=None, max_ratio=5)


def test_the_ratio_gate_refuses_before_writing_anything(tmp_path: Path) -> None:
    """An obvious bomb should cost zero bytes on disk."""
    archive = _zip_with(tmp_path, "ratio.zip", {"big.bin": BOMB_PAYLOAD})
    out = tmp_path / "out"
    with pytest.raises(SecurityError):
        extract_archive(archive, out, max_bytes=None, max_ratio=5)
    assert list(out.rglob("*")) == [], "nothing should have been written"


# ---------------------------------------------------------------------------
# An archive that lies about its size
# ---------------------------------------------------------------------------
def test_a_member_cannot_deliver_more_than_it_declares(tmp_path: Path) -> None:
    """Establishes *why* the declared-size gate is sound rather than advisory.

    Both zipfile and tarfile stop reading a member at its declared length, so
    understating that length cannot smuggle extra bytes past the early gate --
    it truncates the member instead, and for ZIP the CRC then fails. This test
    pins that assumption down: if a future Python ever stopped bounding reads,
    the declared-size gate would silently weaken, and this would catch it.
    """
    archive = _zip_with(tmp_path, "liar.zip", {"big.bin": BOMB_PAYLOAD})

    raw = archive.read_bytes()
    real_size = len(BOMB_PAYLOAD).to_bytes(4, "little")
    assert raw.count(real_size) >= 1, "expected the declared size in the headers"
    archive.write_bytes(raw.replace(real_size, (8).to_bytes(4, "little")))

    with zipfile.ZipFile(archive) as zf:
        member = zf.infolist()[0]
        assert member.file_size == 8, "the archive should now understate its size"
        with pytest.raises(zipfile.BadZipFile):
            zf.open(member).read()


def test_a_tampered_archive_is_refused_with_this_module_s_error(tmp_path: Path) -> None:
    """A corrupt archive must not surface a raw zipfile/tarfile exception.

    Callers are written to catch ToolkitError; a BadZipFile escaping the module
    would sail straight past them.
    """
    archive = _zip_with(tmp_path, "liar.zip", {"big.bin": BOMB_PAYLOAD})
    raw = archive.read_bytes()
    archive.write_bytes(raw.replace(len(BOMB_PAYLOAD).to_bytes(4, "little"), (8).to_bytes(4, "little")))

    out = tmp_path / "out"
    with pytest.raises(OperationError, match="Corrupt or unreadable"):
        extract_archive(archive, out, max_bytes=None, max_ratio=None)

    # And nothing oversized was left behind.
    written = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    assert written < 1024, "a refused archive must not leave a large payload on disk"


def test_verify_reports_a_tampered_archive_as_corrupt(tmp_path: Path) -> None:
    archive = _zip_with(tmp_path, "liar.zip", {"big.bin": BOMB_PAYLOAD})
    raw = archive.read_bytes()
    archive.write_bytes(raw.replace(len(BOMB_PAYLOAD).to_bytes(4, "little"), (8).to_bytes(4, "little")))
    result = verify_archive(archive)
    assert result.extra["status"] == "corrupt"


def test_traversal_is_still_blocked_alongside_the_new_limits(tmp_path: Path) -> None:
    """The bomb guard must not have displaced the zip-slip guard."""
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escaped.txt", b"pwned")
    with pytest.raises(SecurityError, match="traversal"):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "escaped.txt").exists()
