"""Smart file organizer.

Moves files from a source directory into tidy sub-folders based on a chosen
strategy: by category (Images/Videos/...), by raw extension, by date, or by
size bucket. Every move is collision-safe (never overwrites) and honours
dry-run so users can preview the result first.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from core.base import Action, OperationResult
from utils.fs import categorize, ensure_directory, extension_of, human_readable_size
from utils.logging_config import get_logger
from utils.security import iter_files, unique_destination, validate_path

logger = get_logger("organizer")

# A strategy maps a file to the *name of the sub-folder* it belongs in.
Strategy = Callable[[Path], str]

# NOTE: bucket labels become folder names, so they must avoid characters that
# are illegal on Windows ( < > : " / \ | ? * ). Hence "under"/"over" instead of
# the "<"/">" symbols.
_SIZE_BUCKETS = (
    (1024 * 1024, "Small (under 1MB)"),
    (100 * 1024 * 1024, "Medium (1-100MB)"),
    (1024 * 1024 * 1024, "Large (100MB-1GB)"),
)


def _by_category(path: Path) -> str:
    return categorize(path)


def _by_extension(path: Path) -> str:
    ext = extension_of(path)
    return ext.upper() if ext else "No Extension"


def _by_modified_date(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m")


def _by_created_date(path: Path) -> str:
    stat = path.stat()
    ts = getattr(stat, "st_ctime", stat.st_mtime)
    return datetime.fromtimestamp(ts).strftime("%Y-%m")


def _by_size(path: Path) -> str:
    size = path.stat().st_size
    for threshold, label in _SIZE_BUCKETS:
        if size < threshold:
            return label
    return "Huge (over 1GB)"


STRATEGIES: dict[str, Strategy] = {
    "category": _by_category,
    "extension": _by_extension,
    "modified": _by_modified_date,
    "created": _by_created_date,
    "size": _by_size,
}


def organize(
    source: str | Path,
    *,
    strategy: str = "category",
    recursive: bool = False,
    dry_run: bool = False,
    skip_hidden: bool = True,
    custom_rules: dict[str, str] | None = None,
) -> OperationResult:
    """Organize files in *source* into sub-folders using *strategy*.

    Parameters
    ----------
    strategy:
        One of ``category``, ``extension``, ``modified``, ``created``, ``size``.
    custom_rules:
        Optional mapping of extension -> folder name that overrides the chosen
        strategy for specific extensions (e.g. ``{"psd": "Design"}``).
    """
    base = validate_path(source, must_exist=True, for_write=True)
    if not base.is_dir():
        from utils.exceptions import OperationError

        raise OperationError(f"Source must be a directory: {base}")

    if strategy not in STRATEGIES:
        from utils.exceptions import OperationError

        raise OperationError(f"Unknown strategy '{strategy}'. Choose from {', '.join(STRATEGIES)}.")

    classify = STRATEGIES[strategy]
    custom_rules = {k.lower().lstrip("."): v for k, v in (custom_rules or {}).items()}
    result = OperationResult(operation="organize", dry_run=dry_run, extra={"strategy": strategy})

    # Snapshot the file list first so newly-created folders are not re-scanned.
    files = [f for f in iter_files(base, recursive=recursive, skip_hidden=skip_hidden) if f.is_file()]

    for file_path in files:
        try:
            folder_name = custom_rules.get(extension_of(file_path)) or classify(file_path)
            target_dir = base / folder_name

            # Skip files that already live in their destination folder.
            if file_path.parent == target_dir:
                continue

            destination = unique_destination(target_dir / file_path.name)
            size = file_path.stat().st_size

            if dry_run:
                result.add(
                    Action(
                        kind="move",
                        source=str(file_path),
                        destination=str(destination),
                        size=size,
                        note="dry-run",
                    )
                )
                continue

            ensure_directory(target_dir)
            shutil.move(str(file_path), str(destination))
            result.add(Action(kind="move", source=str(file_path), destination=str(destination), size=size))
        except (OSError, ValueError) as exc:
            result.error(f"{file_path}: {exc}")
            logger.warning("Failed to organize %s: %s", file_path, exc)

    logger.info(
        "%sOrganized %d file(s) (%s) by %s",
        "[dry-run] " if dry_run else "",
        result.items,
        human_readable_size(result.bytes),
        strategy,
    )
    return result.finish()
