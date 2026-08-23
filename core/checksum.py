"""File hashing and integrity verification.

Hashing is streamed in fixed-size chunks so that even multi-gigabyte files are
processed with a tiny, constant memory footprint. SHA-256 is the default; SHA-1
and MD5 are offered for interoperability with legacy manifests (never for
security decisions).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from core.base import Action, OperationResult
from utils.exceptions import IntegrityError, OperationError
from utils.fs import human_readable_size
from utils.logging_config import get_logger
from utils.security import iter_files, validate_path

logger = get_logger("checksum")

SUPPORTED_ALGORITHMS = ("sha256", "sha1", "md5")
DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def hash_file(
    path: str | Path,
    *,
    algorithm: str = "sha256",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> str:
    """Return the hex digest of *path* using *algorithm*.

    Raises :class:`OperationError` for unknown algorithms or unreadable files.
    """
    algorithm = algorithm.lower()
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise OperationError(
            f"Unsupported hash algorithm '{algorithm}'. Choose from {', '.join(SUPPORTED_ALGORITHMS)}."
        )

    file_path = validate_path(path, must_exist=True)
    if not file_path.is_file():
        raise OperationError(f"Not a file: {file_path}")

    digest = hashlib.new(algorithm)
    try:
        with file_path.open("rb") as handle:
            for block in iter(lambda: handle.read(chunk_size), b""):
                digest.update(block)
    except OSError as exc:
        raise OperationError(f"Cannot read {file_path}: {exc}") from exc
    return digest.hexdigest()


def hash_many(
    paths: Iterable[Path],
    *,
    algorithm: str = "sha256",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> dict[Path, str]:
    """Hash each path, skipping (and logging) individually unreadable files."""
    results: dict[Path, str] = {}
    for path in paths:
        try:
            results[path] = hash_file(path, algorithm=algorithm, chunk_size=chunk_size)
        except OperationError as exc:
            logger.warning("Skipping %s: %s", path, exc)
    return results


def generate_manifest(
    root: str | Path,
    *,
    algorithm: str = "sha256",
    recursive: bool = True,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> OperationResult:
    """Hash every file under *root* and return the digests as an operation result.

    The digests are placed in ``result.extra['manifest']`` as a mapping of
    relative path -> digest, ready to be serialised into a report.
    """
    base = validate_path(root, must_exist=True)
    result = OperationResult(operation="checksum", extra={"algorithm": algorithm})
    manifest: dict[str, str] = {}

    for file_path in iter_files(base, recursive=recursive):
        try:
            digest = hash_file(file_path, algorithm=algorithm, chunk_size=chunk_size)
        except OperationError as exc:
            result.error(f"{file_path}: {exc}")
            continue
        rel = str(file_path.relative_to(base)) if base.is_dir() else file_path.name
        manifest[rel] = digest
        size = file_path.stat().st_size
        result.add(Action(kind="hash", source=str(file_path), size=size, note=digest))

    result.extra["manifest"] = manifest
    logger.info(
        "Hashed %d file(s) (%s) under %s",
        result.items,
        human_readable_size(result.bytes),
        base,
    )
    return result.finish()


def verify_file(path: str | Path, expected: str, *, algorithm: str = "sha256") -> bool:
    """Return ``True`` when *path* matches *expected*; raise on mismatch info.

    A convenience wrapper used by backup verification. Returns a boolean rather
    than raising so callers can decide how to react, but logs the mismatch.
    """
    actual = hash_file(path, algorithm=algorithm)
    matches = actual.lower() == expected.lower()
    if not matches:
        logger.error("Integrity mismatch for %s: expected %s, got %s", path, expected, actual)
    return matches


def verify_manifest(
    root: str | Path,
    manifest: dict[str, str],
    *,
    algorithm: str = "sha256",
) -> OperationResult:
    """Verify files under *root* against a previously generated *manifest*."""
    base = validate_path(root, must_exist=True)
    result = OperationResult(operation="verify", extra={"algorithm": algorithm})
    ok = 0
    for rel, expected in manifest.items():
        target = base / rel
        if not target.exists():
            result.error(f"Missing file: {rel}")
            result.add(Action(kind="missing", source=str(target), note="absent"))
            continue
        if verify_file(target, expected, algorithm=algorithm):
            ok += 1
            result.add(Action(kind="verified", source=str(target), note="ok"))
        else:
            result.error(f"Corrupted / modified: {rel}")
            result.add(Action(kind="corrupt", source=str(target), note="mismatch"))
    result.extra["verified_ok"] = ok
    result.extra["failed"] = len(result.errors)
    if result.errors:
        logger.warning("Manifest verification found %d problem(s)", len(result.errors))
    return result.finish()


def ensure_integrity(path: str | Path, expected: str, *, algorithm: str = "sha256") -> None:
    """Raise :class:`IntegrityError` unless *path* matches *expected*."""
    if not verify_file(path, expected, algorithm=algorithm):
        raise IntegrityError(f"Integrity check failed for {path}")
