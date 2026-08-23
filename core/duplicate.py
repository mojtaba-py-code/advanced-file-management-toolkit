"""Duplicate file detection and resolution.

Detection is two-phased for efficiency: files are first grouped by size (a
cheap ``stat`` call), and only same-size candidates are hashed. This avoids
reading the contents of files that cannot possibly be duplicates.

The "original" in each group is the file with the earliest modification time;
every other member is treated as a duplicate that can be reported, moved, or
deleted (always behind confirmation / dry-run).
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path

from core.base import Action, OperationResult
from core.checksum import hash_file
from utils.exceptions import OperationError
from utils.fs import ensure_directory, human_readable_size
from utils.logging_config import get_logger
from utils.security import iter_files, require_confirmation, unique_destination, validate_path

logger = get_logger("duplicate")


def find_duplicates(
    root: str | Path,
    *,
    recursive: bool = True,
    algorithm: str = "sha256",
    skip_hidden: bool = False,
) -> dict[str, list[Path]]:
    """Return a mapping of ``digest -> [paths]`` for groups with >1 member."""
    base = validate_path(root, must_exist=True)

    by_size: dict[int, list[Path]] = defaultdict(list)
    for file_path in iter_files(base, recursive=recursive, skip_hidden=skip_hidden):
        try:
            by_size[file_path.stat().st_size].append(file_path)
        except OSError as exc:
            logger.warning("Cannot stat %s: %s", file_path, exc)

    duplicates: dict[str, list[Path]] = defaultdict(list)
    for size, candidates in by_size.items():
        if size == 0 or len(candidates) < 2:
            continue  # Unique size (or empty files) cannot be content duplicates.
        for file_path in candidates:
            try:
                digest = hash_file(file_path, algorithm=algorithm)
            except OperationError as exc:
                logger.warning("Skipping %s: %s", file_path, exc)
                continue
            duplicates[digest].append(file_path)

    # Keep only real duplicate groups.
    return {digest: paths for digest, paths in duplicates.items() if len(paths) > 1}


def _original_and_copies(paths: list[Path]) -> tuple[Path, list[Path]]:
    """Pick the oldest file as the original; the rest are duplicates."""
    ordered = sorted(paths, key=lambda p: p.stat().st_mtime)
    return ordered[0], ordered[1:]


def resolve_duplicates(
    root: str | Path,
    *,
    action: str = "report",
    move_to: str | Path | None = None,
    recursive: bool = True,
    algorithm: str = "sha256",
    dry_run: bool = False,
    force: bool = False,
    skip_hidden: bool = False,
) -> OperationResult:
    """Find duplicates under *root* and optionally resolve them.

    Parameters
    ----------
    action:
        ``report`` (default, non-destructive), ``move`` or ``delete``.
    move_to:
        Destination directory required when ``action='move'``.
    """
    if action not in ("report", "move", "delete"):
        raise OperationError(f"Unknown action '{action}'. Use report|move|delete.")

    if action in ("move", "delete"):
        # Reporting is read-only anywhere; removing or relocating files out of a
        # protected OS location is not.
        validate_path(root, must_exist=True, for_write=True)

    groups = find_duplicates(root, recursive=recursive, algorithm=algorithm, skip_hidden=skip_hidden)
    result = OperationResult(
        operation="duplicate",
        dry_run=dry_run,
        extra={"action": action, "groups": len(groups)},
    )

    move_dir: Path | None = None
    if action == "move":
        if move_to is None:
            raise OperationError("action='move' requires move_to.")
        move_dir = validate_path(move_to, must_exist=False, for_write=True)

    if action == "delete" and groups and not dry_run:
        total = sum(len(paths) - 1 for paths in groups.values())
        require_confirmation(
            f"Delete {total} duplicate file(s) across {len(groups)} group(s)?",
            force=force,
        )

    reclaimable = 0
    for paths in groups.values():
        original, copies = _original_and_copies(paths)
        for copy_path in copies:
            size = copy_path.stat().st_size
            reclaimable += size
            note = f"dup-of:{original.name}"

            if action == "report" or dry_run:
                result.add(
                    Action(
                        kind="duplicate",
                        source=str(copy_path),
                        destination=str(original),
                        size=size,
                        note=note,
                    )
                )
                continue

            try:
                if action == "delete":
                    copy_path.unlink()
                    result.add(Action(kind="delete", source=str(copy_path), size=size, note=note))
                elif action == "move" and move_dir is not None:
                    ensure_directory(move_dir)
                    destination = unique_destination(move_dir / copy_path.name)
                    shutil.move(str(copy_path), str(destination))
                    result.add(
                        Action(
                            kind="move",
                            source=str(copy_path),
                            destination=str(destination),
                            size=size,
                            note=note,
                        )
                    )
            except OSError as exc:
                result.error(f"{copy_path}: {exc}")
                logger.warning("Failed to %s %s: %s", action, copy_path, exc)

    result.extra["reclaimable_bytes"] = reclaimable
    result.extra["reclaimable_human"] = human_readable_size(reclaimable)
    logger.info(
        "%sFound %d duplicate group(s); %s reclaimable",
        "[dry-run] " if dry_run else "",
        len(groups),
        human_readable_size(reclaimable),
    )
    return result.finish()
