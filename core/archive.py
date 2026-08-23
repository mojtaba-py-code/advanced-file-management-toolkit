"""Archive management: create, extract and verify ZIP / TAR archives.

Extraction is hardened against the "zip-slip" / "tar-slip" vulnerability: every
member's destination is validated with :func:`safe_join` so a crafted archive
cannot write outside the chosen output directory.
"""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path
from typing import Literal

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


def extract_archive(
    archive: str | Path,
    output: str | Path,
    *,
    dry_run: bool = False,
) -> OperationResult:
    """Safely extract *archive* into *output*, blocking path-traversal members."""
    arc = validate_path(archive, must_exist=True)
    out = validate_path(output, must_exist=False, for_write=True)
    ensure_directory(out)
    result = OperationResult(operation="extract", dry_run=dry_run)

    if zipfile.is_zipfile(arc):
        with zipfile.ZipFile(arc) as zf:
            for member in zf.infolist():
                _guard_member(out, member.filename)
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
                zf.extract(member, out)
                result.add(
                    Action(
                        kind="extract",
                        source=member.filename,
                        destination=str(out / member.filename),
                        size=member.file_size,
                    )
                )
    elif tarfile.is_tarfile(arc):
        with tarfile.open(arc) as tf:
            for entry in tf.getmembers():
                _guard_member(out, entry.name)
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
                tf.extract(entry, out)
                result.add(
                    Action(
                        kind="extract",
                        source=entry.name,
                        destination=str(out / entry.name),
                        size=entry.size,
                    )
                )
    else:
        raise OperationError(f"Unrecognised archive format: {arc}")

    logger.info("%sExtracted %d member(s) from %s", "[dry-run] " if dry_run else "", result.items, arc.name)
    return result.finish()


def _guard_member(output_root: Path, member_name: str) -> None:
    """Raise :class:`SecurityError` if *member_name* would escape *output_root*."""
    if not member_name:
        return
    try:
        safe_join(output_root, *Path(member_name).parts)
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
                    if member.isfile():
                        tf.extractfile(member).read()  # type: ignore[union-attr]
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
