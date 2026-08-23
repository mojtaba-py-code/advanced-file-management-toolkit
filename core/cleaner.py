"""Cleanup utilities: empty folders, zero-byte files and temporary files.

Deletions are always preceded by discovery, so callers can preview exactly
what will be removed. Destructive runs require confirmation (or ``force``) and
respect ``dry_run``.
"""

from __future__ import annotations

from pathlib import Path

from core.base import Action, OperationResult
from utils.fs import is_empty_dir
from utils.logging_config import get_logger
from utils.security import iter_files, require_confirmation, validate_path

logger = get_logger("cleaner")

# Extensions and name patterns commonly used for throwaway files.
_TEMP_SUFFIXES = (".tmp", ".temp", ".bak", ".old", ".swp", ".~", ".part", ".crdownload")
_TEMP_NAMES = ("thumbs.db", ".ds_store", "desktop.ini")


def _is_temp(path: Path) -> bool:
    name = path.name.lower()
    if name in _TEMP_NAMES:
        return True
    if name.endswith("~"):
        return True
    return path.suffix.lower() in _TEMP_SUFFIXES


def find_targets(
    root: str | Path,
    *,
    empty_dirs: bool = True,
    zero_byte: bool = True,
    temp_files: bool = True,
    recursive: bool = True,
) -> dict[str, list[Path]]:
    """Discover cleanup candidates, grouped by category."""
    base = validate_path(root, must_exist=True)
    targets: dict[str, list[Path]] = {"empty_dirs": [], "zero_byte": [], "temp_files": []}

    if zero_byte or temp_files:
        for file_path in iter_files(base, recursive=recursive):
            try:
                if zero_byte and file_path.stat().st_size == 0:
                    targets["zero_byte"].append(file_path)
                elif temp_files and _is_temp(file_path):
                    targets["temp_files"].append(file_path)
            except OSError as exc:
                logger.warning("Cannot stat %s: %s", file_path, exc)

    if empty_dirs:
        # Walk bottom-up so nested empty directories are all detected.
        for directory in sorted((p for p in base.rglob("*") if p.is_dir()), reverse=True):
            if is_empty_dir(directory):
                targets["empty_dirs"].append(directory)

    return targets


def clean(
    root: str | Path,
    *,
    empty_dirs: bool = True,
    zero_byte: bool = True,
    temp_files: bool = True,
    recursive: bool = True,
    dry_run: bool = False,
    force: bool = False,
) -> OperationResult:
    """Remove cleanup targets found under *root*."""
    # Deletion is the most destructive operation in the toolkit, so the OS
    # deny-list is enforced here even though discovery itself is read-only.
    validate_path(root, must_exist=True, for_write=True)
    targets = find_targets(
        root,
        empty_dirs=empty_dirs,
        zero_byte=zero_byte,
        temp_files=temp_files,
        recursive=recursive,
    )
    result = OperationResult(operation="clean", dry_run=dry_run)
    total = sum(len(items) for items in targets.values())

    if total and not dry_run:
        require_confirmation(f"Delete {total} item(s) during cleanup?", force=force)

    # Delete files first, then (now possibly empty) directories.
    for category in ("zero_byte", "temp_files", "empty_dirs"):
        for path in targets[category]:
            try:
                size = 0
                if path.is_file():
                    size = path.stat().st_size
                    if not dry_run:
                        path.unlink()
                elif path.is_dir():
                    if not dry_run:
                        path.rmdir()
                result.add(Action(kind="delete", source=str(path), size=size, note=category))
            except OSError as exc:
                result.error(f"{path}: {exc}")
                logger.warning("Cleanup failed for %s: %s", path, exc)

    result.extra["by_category"] = {k: len(v) for k, v in targets.items()}
    logger.info("%sCleaned %d item(s)", "[dry-run] " if dry_run else "", result.items)
    return result.finish()
