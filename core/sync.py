"""Directory synchronisation: one-way, mirror and two-way modes.

Files are compared by relative path, size and modification time. A file is
considered "changed" when its size differs or the source is newer than the
destination (with a one-second tolerance to absorb filesystem timestamp
granularity differences across platforms).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from core.base import Action, OperationResult
from utils.exceptions import OperationError
from utils.fs import ensure_directory, human_readable_size
from utils.logging_config import get_logger
from utils.security import iter_files, require_confirmation, validate_path

logger = get_logger("sync")

_MTIME_TOLERANCE = 1.0  # seconds


def _relative_map(root: Path) -> dict[str, Path]:
    """Map every file under *root* to its path, keyed by POSIX relative path."""
    mapping: dict[str, Path] = {}
    for file_path in iter_files(root, recursive=True):
        mapping[file_path.relative_to(root).as_posix()] = file_path
    return mapping


def _needs_update(src: Path, dst: Path) -> bool:
    src_stat, dst_stat = src.stat(), dst.stat()
    if src_stat.st_size != dst_stat.st_size:
        return True
    return src_stat.st_mtime - dst_stat.st_mtime > _MTIME_TOLERANCE


def _copy(src: Path, dst: Path) -> None:
    ensure_directory(dst.parent)
    shutil.copy2(src, dst)


def sync(
    source: str | Path,
    destination: str | Path,
    *,
    mode: str = "one-way",
    dry_run: bool = False,
    force: bool = False,
    delete: bool | None = None,
) -> OperationResult:
    """Synchronise *source* into *destination*.

    Modes
    -----
    ``one-way``
        Copy new and changed files from source to destination. Extra files in
        the destination are left untouched.
    ``mirror``
        Like one-way, but also deletes destination files that no longer exist
        in the source (destination becomes an exact copy).
    ``two-way``
        Bidirectional: the newer version of each file wins and is propagated to
        the other side. Nothing is deleted.
    """
    if mode not in ("one-way", "mirror", "two-way"):
        raise OperationError(f"Unknown sync mode '{mode}'. Use one-way|mirror|two-way.")

    src_root = validate_path(source, must_exist=True)
    dst_root = validate_path(destination, must_exist=False, for_write=True)
    if not src_root.is_dir():
        raise OperationError(f"Source must be a directory: {src_root}")
    ensure_directory(dst_root)

    result = OperationResult(operation="sync", dry_run=dry_run, extra={"mode": mode})
    src_files = _relative_map(src_root)
    dst_files = _relative_map(dst_root)

    # --- forward pass: source -> destination ------------------------------
    for rel, src_path in src_files.items():
        dst_path = dst_root / rel
        try:
            if rel not in dst_files:
                size = src_path.stat().st_size
                if not dry_run:
                    _copy(src_path, dst_path)
                result.add(
                    Action(
                        kind="copy", source=str(src_path), destination=str(dst_path), size=size, note="new"
                    )
                )
            elif _needs_update(src_path, dst_path):
                size = src_path.stat().st_size
                if mode == "two-way" and dst_path.stat().st_mtime > src_path.stat().st_mtime:
                    continue  # destination is newer; handled in reverse pass
                if not dry_run:
                    _copy(src_path, dst_path)
                result.add(
                    Action(
                        kind="update",
                        source=str(src_path),
                        destination=str(dst_path),
                        size=size,
                        note="changed",
                    )
                )
        except OSError as exc:
            result.error(f"{src_path}: {exc}")
            logger.warning("Sync failed for %s: %s", src_path, exc)

    # --- reverse pass: destination -> source (two-way only) ---------------
    if mode == "two-way":
        for rel, dst_path in dst_files.items():
            src_path = src_root / rel
            try:
                if rel not in src_files:
                    size = dst_path.stat().st_size
                    if not dry_run:
                        _copy(dst_path, src_path)
                    result.add(
                        Action(
                            kind="copy",
                            source=str(dst_path),
                            destination=str(src_path),
                            size=size,
                            note="new-reverse",
                        )
                    )
                elif (
                    _needs_update(dst_path, src_path) and dst_path.stat().st_mtime > src_path.stat().st_mtime
                ):
                    size = dst_path.stat().st_size
                    if not dry_run:
                        _copy(dst_path, src_path)
                    result.add(
                        Action(
                            kind="update",
                            source=str(dst_path),
                            destination=str(src_path),
                            size=size,
                            note="changed-reverse",
                        )
                    )
            except OSError as exc:
                result.error(f"{dst_path}: {exc}")

    # --- mirror deletions -------------------------------------------------
    should_delete = delete if delete is not None else (mode == "mirror")
    if should_delete and mode != "two-way":
        stale = [rel for rel in dst_files if rel not in src_files]
        if stale and not dry_run:
            require_confirmation(
                f"Mirror will delete {len(stale)} file(s) from {dst_root}. Continue?",
                force=force,
            )
        for rel in stale:
            dst_path = dst_files[rel]
            try:
                size = dst_path.stat().st_size
                if not dry_run:
                    dst_path.unlink()
                result.add(Action(kind="delete", source=str(dst_path), size=size, note="stale"))
            except OSError as exc:
                result.error(f"{dst_path}: {exc}")

    logger.info(
        "%sSync (%s) complete: %d change(s), %s transferred",
        "[dry-run] " if dry_run else "",
        mode,
        result.items,
        human_readable_size(result.bytes),
    )
    return result.finish()
