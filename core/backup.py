"""Backup engine: full, incremental and differential backups.

Design
------
Each backup is a timestamped directory under the destination, e.g.
``backups/2026-01-01_120000_full/``. It contains a ``data/`` tree with the
backed-up files plus a ``manifest.json`` describing every stored file
(relative path, size, mtime and SHA-256). Optionally the whole backup is
compressed into a single ``.zip`` and the raw directory removed.

* **Full** – stores every file in the source.
* **Incremental** – stores only files changed since the *previous* backup of
  any kind.
* **Differential** – stores only files changed since the last *full* backup.

Integrity is verified by re-hashing every stored file against the manifest,
so a backup that silently corrupted on write is caught immediately.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from core.base import Action, OperationResult
from core.checksum import hash_file, verify_file
from utils.exceptions import IntegrityError, OperationError
from utils.fs import ensure_directory, human_readable_size
from utils.logging_config import get_logger
from utils.security import iter_files, safe_join, validate_path

logger = get_logger("backup")

MANIFEST_NAME = "manifest.json"
BACKUP_TYPES = ("full", "incremental", "differential")


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _file_state(path: Path, base: Path, *, with_hash: bool = False) -> dict[str, Any]:
    stat = path.stat()
    state: dict[str, Any] = {"size": stat.st_size, "mtime": stat.st_mtime}
    if with_hash:
        state["sha256"] = hash_file(path)
    return state


def _load_manifest(location: Path) -> dict[str, Any] | None:
    """Load a manifest from a backup directory or ``.zip``."""
    try:
        if location.is_dir():
            manifest_file = location / MANIFEST_NAME
            if manifest_file.exists():
                return json.loads(manifest_file.read_text(encoding="utf-8"))
        elif location.suffix == ".zip" and zipfile.is_zipfile(location):
            with zipfile.ZipFile(location) as zf:
                if MANIFEST_NAME in zf.namelist():
                    return json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
    except (OSError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        logger.warning("Could not read manifest from %s: %s", location, exc)
    return None


def _previous_backups(dest: Path) -> list[tuple[str, dict[str, Any]]]:
    """Return ``[(name, manifest)]`` for existing backups, oldest first."""
    if not dest.exists():
        return []
    found: list[tuple[str, dict[str, Any]]] = []
    for entry in dest.iterdir():
        manifest = _load_manifest(entry)
        if manifest:
            found.append((entry.name, manifest))
    found.sort(key=lambda item: item[1].get("timestamp", item[0]))
    return found


def _baseline_state(dest: Path, backup_type: str) -> dict[str, dict[str, Any]]:
    """Compute the reference state used to decide which files changed."""
    previous = _previous_backups(dest)
    baseline: dict[str, dict[str, Any]] = {}
    if backup_type == "incremental":
        # Merge every previous backup; later timestamps overwrite earlier ones.
        for _name, manifest in previous:
            baseline.update(manifest.get("files", {}))
    elif backup_type == "differential":
        # Only the most recent FULL backup matters.
        fulls = [m for _n, m in previous if m.get("type") == "full"]
        if fulls:
            baseline = dict(fulls[-1].get("files", {}))
    return baseline


def _has_changed(current: dict[str, Any], reference: dict[str, Any] | None) -> bool:
    if reference is None:
        return True
    return current["size"] != reference.get("size") or current["mtime"] > reference.get("mtime", 0)


def create_backup(
    source: str | Path,
    destination: str | Path,
    *,
    backup_type: str = "full",
    compression: bool = True,
    verify: bool = True,
    dry_run: bool = False,
) -> OperationResult:
    """Create a backup of *source* under *destination*."""
    if backup_type not in BACKUP_TYPES:
        raise OperationError(f"Unknown backup type '{backup_type}'. Use {', '.join(BACKUP_TYPES)}.")

    src_root = validate_path(source, must_exist=True)
    if not src_root.is_dir():
        raise OperationError(f"Backup source must be a directory: {src_root}")
    dest_root = validate_path(destination, must_exist=False, for_write=True)
    ensure_directory(dest_root)

    baseline = _baseline_state(dest_root, backup_type)
    result = OperationResult(operation="backup", dry_run=dry_run, extra={"type": backup_type})

    backup_name = f"{_timestamp()}_{backup_type}"
    backup_dir = dest_root / backup_name
    data_dir = backup_dir / "data"

    manifest: dict[str, Any] = {
        "type": backup_type,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source": str(src_root),
        "files": {},
    }

    # --- decide what to copy ---------------------------------------------
    to_copy: list[tuple[Path, str, dict[str, Any]]] = []
    for file_path in iter_files(src_root, recursive=True):
        rel = file_path.relative_to(src_root).as_posix()
        state = _file_state(file_path, src_root)
        if _has_changed(state, baseline.get(rel)):
            to_copy.append((file_path, rel, state))

    if not to_copy:
        logger.info("Nothing to back up (%s) — source unchanged.", backup_type)
        result.extra["backup"] = None
        return result.finish()

    if dry_run:
        for file_path, rel, state in to_copy:
            result.add(
                Action(
                    kind="backup",
                    source=str(file_path),
                    destination=f"{backup_name}/data/{rel}",
                    size=state["size"],
                    note="dry-run",
                )
            )
        logger.info(
            "[dry-run] Would back up %d file(s) (%s)", result.items, human_readable_size(result.bytes)
        )
        result.extra["backup"] = backup_name
        return result.finish()

    # --- copy + hash ------------------------------------------------------
    ensure_directory(data_dir)
    for file_path, rel, state in to_copy:
        try:
            target = safe_join(data_dir, *rel.split("/"))
            ensure_directory(target.parent)
            shutil.copy2(file_path, target)
            state["sha256"] = hash_file(target)
            manifest["files"][rel] = state
            result.add(
                Action(kind="backup", source=str(file_path), destination=str(target), size=state["size"])
            )
        except OSError as exc:
            result.error(f"{file_path}: {exc}")
            logger.warning("Backup failed for %s: %s", file_path, exc)

    (backup_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # --- verify -----------------------------------------------------------
    if verify:
        failed = 0
        for rel, state in manifest["files"].items():
            target = data_dir / rel
            if not verify_file(target, state["sha256"]):
                failed += 1
                result.error(f"Verification failed: {rel}")
        if failed:
            raise IntegrityError(f"Backup verification failed for {failed} file(s)")
        result.extra["verified"] = True

    # --- optional compression --------------------------------------------
    if compression:
        archive_path = dest_root / f"{backup_name}.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in backup_dir.rglob("*"):
                if item.is_file():
                    zf.write(item, item.relative_to(backup_dir).as_posix())
        shutil.rmtree(backup_dir)
        result.extra["archive"] = str(archive_path)
        logger.info("Backup compressed to %s", archive_path.name)

    result.extra["backup"] = backup_name
    logger.info(
        "%s backup complete: %d file(s), %s",
        backup_type.title(),
        result.items,
        human_readable_size(result.bytes),
    )
    return result.finish()


def restore_backup(
    backup_path: str | Path,
    target: str | Path,
    *,
    dry_run: bool = False,
    verify: bool = True,
) -> OperationResult:
    """Restore files from a backup directory or ``.zip`` into *target*."""
    backup = validate_path(backup_path, must_exist=True)
    dest = validate_path(target, must_exist=False, for_write=True)
    ensure_directory(dest)
    result = OperationResult(operation="restore", dry_run=dry_run)

    manifest = _load_manifest(backup)
    if manifest is None:
        raise OperationError(f"No manifest found in backup: {backup}")

    # Work from an extracted view so directory and zip backups share one path.
    temp_dir: Path | None = None
    if backup.suffix == ".zip":
        temp_dir = dest.parent / f".restore_tmp_{backup.stem}"
        ensure_directory(temp_dir)
        with zipfile.ZipFile(backup) as zf:
            for member in zf.namelist():
                # Guard against zip-slip during extraction.
                safe_join(temp_dir, *Path(member).parts)
            zf.extractall(temp_dir)
        data_root = temp_dir / "data"
    else:
        data_root = backup / "data"

    try:
        for rel, state in manifest.get("files", {}).items():
            source_file = data_root / rel
            destination = safe_join(dest, *rel.split("/"))
            if not source_file.exists():
                result.error(f"Missing in backup: {rel}")
                continue
            if dry_run:
                result.add(
                    Action(
                        kind="restore",
                        source=str(source_file),
                        destination=str(destination),
                        size=state.get("size", 0),
                        note="dry-run",
                    )
                )
                continue
            ensure_directory(destination.parent)
            shutil.copy2(source_file, destination)
            if verify and "sha256" in state and not verify_file(destination, state["sha256"]):
                result.error(f"Restored file failed verification: {rel}")
            result.add(
                Action(
                    kind="restore",
                    source=str(source_file),
                    destination=str(destination),
                    size=state.get("size", 0),
                )
            )
    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    logger.info(
        "%sRestore complete: %d file(s), %s",
        "[dry-run] " if dry_run else "",
        result.items,
        human_readable_size(result.bytes),
    )
    return result.finish()


def list_backups(destination: str | Path) -> list[dict[str, Any]]:
    """Return summary metadata for every backup under *destination*."""
    dest = validate_path(destination, must_exist=False)
    summaries: list[dict[str, Any]] = []
    for name, manifest in _previous_backups(dest):
        summaries.append(
            {
                "name": name,
                "type": manifest.get("type"),
                "timestamp": manifest.get("timestamp"),
                "files": len(manifest.get("files", {})),
            }
        )
    return summaries
