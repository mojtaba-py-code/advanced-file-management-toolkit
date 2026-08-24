"""Archive management: create, extract and verify ZIP / TAR archives.

Extraction is hardened against the "zip-slip" / "tar-slip" vulnerability: every
member's destination is validated with :func:`safe_join` so a crafted archive
cannot write outside the chosen output directory.
"""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path
from typing import IO, Literal

from core.base import Action, OperationResult
from utils.exceptions import OperationError, SecurityError
from utils.fs import ensure_directory, human_readable_size
from utils.logging_config import get_logger
from utils.security import iter_files, safe_join, unique_destination, validate_path

logger = get_logger("archive")

# Map a requested format to its tarfile write mode. The value type is narrowed
# to a Literal so tarfile.open()'s overloads resolve.
_TarWriteMode = Literal["w", "w:gz", "w:bz2"]
_TAR_MODES: dict[str, _TarWriteMode] = {
    "tar": "w",
    "tar.gz": "w:gz",
    "tgz": "w:gz",
    "tar.bz2": "w:bz2",
}


def create_archive(
    source: str | Path,
    output: str | Path,
    *,
    fmt: str = "zip",
    dry_run: bool = False,
) -> OperationResult:
    """Compress *source* (file or directory) into an archive at *output*.

    ``fmt`` may be ``zip``, ``tar``, ``tar.gz`` (aka ``tgz``) or ``tar.bz2``.
    """
    src = validate_path(source, must_exist=True)
    out = validate_path(output, must_exist=False, for_write=True)
    out = unique_destination(out)
    result = OperationResult(operation="archive", dry_run=dry_run, extra={"format": fmt})

    files = list(iter_files(src, recursive=True)) if src.is_dir() else [src]
    arc_base = src if src.is_dir() else src.parent

    if dry_run:
        for file_path in files:
            result.add(
                Action(
                    kind="compress",
                    source=str(file_path),
                    destination=str(out),
                    size=file_path.stat().st_size,
                    note="dry-run",
                )
            )
        return result.finish()

    ensure_directory(out.parent)
    try:
        if fmt == "zip":
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in files:
                    arcname = file_path.relative_to(arc_base).as_posix()
                    zf.write(file_path, arcname)
                    result.add(
                        Action(
                            kind="compress",
                            source=str(file_path),
                            destination=arcname,
                            size=file_path.stat().st_size,
                        )
                    )
        elif fmt in _TAR_MODES:
            with tarfile.open(out, _TAR_MODES[fmt]) as tf:
                for file_path in files:
                    arcname = file_path.relative_to(arc_base).as_posix()
                    tf.add(file_path, arcname=arcname)
                    result.add(
                        Action(
                            kind="compress",
                            source=str(file_path),
                            destination=arcname,
                            size=file_path.stat().st_size,
                        )
                    )
        else:
            raise OperationError(f"Unsupported archive format '{fmt}'.")
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise OperationError(f"Failed to create archive {out}: {exc}") from exc

    result.extra["archive"] = str(out)
    logger.info("Created %s archive %s (%s)", fmt, out.name, human_readable_size(result.bytes))
    return result.finish()


# ---------------------------------------------------------------------------
# Decompression limits
# ---------------------------------------------------------------------------
# A crafted archive can expand to enormously more than its size on disk (the
# "zip bomb" / "decompression bomb" class). Extraction is therefore bounded in
# two independent ways.
#
# First, a cheap gate on the sizes the archive declares, which refuses an
# obvious bomb before a single byte reaches disk. This is sound rather than
# advisory because both zipfile and tarfile stop reading a member at its
# declared length, so a member cannot quietly deliver more than it claims.
#
# Second, a running total of bytes actually written, enforced while streaming.
# That is what catches the cumulative case -- many individually modest members
# adding up -- and it keeps the guarantee if the declared figure and the real
# one ever diverge.
#
# Streaming in chunks also means no member is ever held in memory in full,
# which matters as much as the disk ceiling on a small machine.
DEFAULT_MAX_EXTRACT_BYTES = 2 * 1024**3  # 2 GiB
DEFAULT_MAX_COMPRESSION_RATIO = 200
_COPY_CHUNK = 1024 * 1024


class _Budget:
    """A shrinking allowance of bytes, shared across every member extracted."""

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.written = 0

    def spend(self, count: int, *, member: str) -> None:
        self.written += count
        if self.limit is not None and self.written > self.limit:
            raise SecurityError(
                f"Refusing to continue extracting {member!r}: expanded output "
                f"passed the {human_readable_size(self.limit)} limit. This is "
                f"characteristic of a decompression bomb. Raise max_bytes if the "
                f"archive is genuinely this large."
            )


def _copy_capped(source: IO[bytes], destination: Path, budget: _Budget, member: str) -> int:
    """Stream *source* to *destination*, aborting the moment *budget* runs out.

    Chunked rather than a single read so a member that lies about its size
    cannot force the whole thing into memory before the limit is noticed.
    """
    written = 0
    with destination.open("wb") as handle:
        while True:
            chunk = source.read(_COPY_CHUNK)
            if not chunk:
                break
            budget.spend(len(chunk), member=member)
            handle.write(chunk)
            written += len(chunk)
    return written


def _check_declared_expansion(
    archive_size: int, declared: int, *, max_bytes: int | None, max_ratio: int | None
) -> None:
    """Reject an archive whose own header already admits it is a bomb.

    Cheap, and it means an obvious bomb is refused before a single byte is
    written. It is a first gate only — never the sole defence.
    """
    if max_bytes is not None and declared > max_bytes:
        raise SecurityError(
            f"Refusing to extract: the archive declares {human_readable_size(declared)} "
            f"of content, over the {human_readable_size(max_bytes)} limit."
        )
    if max_ratio is not None and archive_size > 0 and declared / archive_size > max_ratio:
        raise SecurityError(
            f"Refusing to extract: the archive declares a "
            f"{declared / archive_size:.0f}:1 expansion ratio, over the "
            f"{max_ratio}:1 limit. This is characteristic of a decompression bomb."
        )


def extract_archive(
    archive: str | Path,
    output: str | Path,
    *,
    dry_run: bool = False,
    max_bytes: int | None = DEFAULT_MAX_EXTRACT_BYTES,
    max_ratio: int | None = DEFAULT_MAX_COMPRESSION_RATIO,
) -> OperationResult:
    """Safely extract *archive* into *output*.

    Blocks path-traversal members, skips non-regular members, and bounds the
    expanded output so a decompression bomb cannot fill the disk. Pass
    ``max_bytes=None`` to lift the ceiling for an archive you trust.
    """
    arc = validate_path(archive, must_exist=True)
    out = validate_path(output, must_exist=False, for_write=True)
    ensure_directory(out)
    result = OperationResult(operation="extract", dry_run=dry_run)
    budget = _Budget(max_bytes)
    archive_size = arc.stat().st_size

    try:
        if zipfile.is_zipfile(arc):
            with zipfile.ZipFile(arc) as zf:
                members = zf.infolist()
                _check_declared_expansion(
                    archive_size,
                    sum(m.file_size for m in members),
                    max_bytes=max_bytes,
                    max_ratio=max_ratio,
                )
                for member in members:
                    target = _guard_member(out, member.filename)
                    if dry_run:
                        result.add(
                            Action(
                                kind="extract",
                                source=member.filename,
                                destination=str(out),
                                size=member.file_size,
                                note="dry-run",
                            )
                        )
                        continue
                    if target is None or member.is_dir():
                        if target is not None:
                            ensure_directory(target)
                        continue
                    ensure_directory(target.parent)
                    with zf.open(member) as source:
                        written = _copy_capped(source, target, budget, member.filename)
                    result.add(
                        Action(
                            kind="extract",
                            source=member.filename,
                            destination=str(target),
                            size=written,
                        )
                    )
        elif tarfile.is_tarfile(arc):
            with tarfile.open(arc) as tf:
                entries = tf.getmembers()
                _check_declared_expansion(
                    archive_size,
                    sum(e.size for e in entries if e.isfile()),
                    max_bytes=max_bytes,
                    max_ratio=max_ratio,
                )
                for entry in entries:
                    target = _guard_member(out, entry.name)
                    if not (entry.isfile() or entry.isdir()):
                        result.error(f"Skipped non-regular member: {entry.name}")
                        continue
                    if dry_run:
                        result.add(
                            Action(
                                kind="extract",
                                source=entry.name,
                                destination=str(out),
                                size=entry.size,
                                note="dry-run",
                            )
                        )
                        continue
                    if target is None or entry.isdir():
                        if target is not None:
                            ensure_directory(target)
                        continue
                    stream = tf.extractfile(entry)
                    if stream is None:  # pragma: no cover - guarded by isfile() above
                        result.error(f"Could not read member: {entry.name}")
                        continue
                    ensure_directory(target.parent)
                    with stream:
                        written = _copy_capped(stream, target, budget, entry.name)
                    result.add(
                        Action(
                            kind="extract",
                            source=entry.name,
                            destination=str(target),
                            size=written,
                        )
                    )
        else:
            raise OperationError(f"Unrecognised archive format: {arc}")
    except (zipfile.BadZipFile, tarfile.TarError, EOFError) as exc:
        # A truncated or tampered archive must surface as this module's own
        # error type, not as a raw library exception the caller never catches.
        raise OperationError(f"Corrupt or unreadable archive {arc}: {exc}") from exc

    logger.info("%sExtracted %d member(s) from %s", "[dry-run] " if dry_run else "", result.items, arc.name)
    return result.finish()


def _guard_member(output_root: Path, member_name: str) -> Path | None:
    """Return the safe destination for *member_name*, or ``None`` if it is empty.

    Raises :class:`SecurityError` when the member would land outside
    *output_root*. Returning the path, rather than only validating it, is what
    lets the caller write through the checked location instead of handing the
    raw member name back to the archive library.
    """
    if not member_name:
        return None
    try:
        return safe_join(output_root, *Path(member_name).parts)
    except SecurityError as exc:
        raise SecurityError(f"Blocked path-traversal archive member: {member_name}") from exc


def verify_archive(archive: str | Path) -> OperationResult:
    """Test archive integrity without extracting anything."""
    arc = validate_path(archive, must_exist=True)
    result = OperationResult(operation="verify-archive")
    try:
        if zipfile.is_zipfile(arc):
            with zipfile.ZipFile(arc) as zf:
                bad = zf.testzip()
                if bad is not None:
                    result.error(f"Corrupt entry: {bad}")
                    result.extra["status"] = "corrupt"
                else:
                    result.extra["status"] = "ok"
        elif tarfile.is_tarfile(arc):
            with tarfile.open(arc) as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    stream = tf.extractfile(member)
                    if stream is None:  # pragma: no cover - guarded by isfile()
                        continue
                    # Read in chunks: a single .read() would pull an arbitrarily
                    # large member into memory just to check it decompresses.
                    with stream:
                        while stream.read(_COPY_CHUNK):
                            pass
                result.extra["status"] = "ok"
        else:
            # A file whose magic no longer matches any known archive format is
            # treated as corrupt rather than raising, so 'verify' always reports.
            result.error(f"Unrecognised or corrupted archive: {arc}")
            result.extra["status"] = "corrupt"
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        result.error(str(exc))
        result.extra["status"] = "corrupt"
    logger.info("Archive %s verification: %s", arc.name, result.extra.get("status", "unknown"))
    return result.finish()
