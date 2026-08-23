"""File search engine.

Supports composable predicates: name globbing, regular expressions, extension,
size ranges, modification-date ranges, textual content search and hash match.
All active criteria must match (logical AND), which keeps the mental model
simple and predictable.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.base import Action, OperationResult
from core.checksum import hash_file
from utils.exceptions import OperationError
from utils.fs import human_readable_size
from utils.logging_config import get_logger
from utils.security import iter_files, validate_path

logger = get_logger("search")

Predicate = Callable[[Path], bool]
_CONTENT_CHUNK = 65536


@dataclass
class SearchCriteria:
    """A bundle of optional search constraints (all applied with AND)."""

    name: str | None = None  # glob pattern, e.g. "*.log"
    regex: str | None = None  # regex matched against the file name
    extension: str | None = None  # e.g. "pdf" or ".pdf"
    min_size: int | None = None  # bytes
    max_size: int | None = None  # bytes
    modified_after: datetime | None = None
    modified_before: datetime | None = None
    content: str | None = None  # substring searched inside text files
    file_hash: str | None = None  # exact SHA-256 match
    case_sensitive: bool = False

    def build(self) -> list[Predicate]:
        predicates: list[Predicate] = []

        if self.name:
            pattern = self.name if self.case_sensitive else self.name.lower()

            def _match_name(p: Path, pat: str = pattern) -> bool:
                target = p.name if self.case_sensitive else p.name.lower()
                return fnmatch.fnmatch(target, pat)

            predicates.append(_match_name)

        if self.regex:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            try:
                compiled = re.compile(self.regex, flags)
            except re.error as exc:
                raise OperationError(f"Invalid regex '{self.regex}': {exc}") from exc
            predicates.append(lambda p: compiled.search(p.name) is not None)

        if self.extension:
            wanted = self.extension.lower().lstrip(".")
            predicates.append(lambda p: p.suffix.lower().lstrip(".") == wanted)

        if self.min_size is not None:
            predicates.append(lambda p: p.stat().st_size >= self.min_size)  # type: ignore[operator]
        if self.max_size is not None:
            predicates.append(lambda p: p.stat().st_size <= self.max_size)  # type: ignore[operator]

        if self.modified_after is not None:
            after_ts = self.modified_after.timestamp()
            predicates.append(lambda p: p.stat().st_mtime >= after_ts)
        if self.modified_before is not None:
            before_ts = self.modified_before.timestamp()
            predicates.append(lambda p: p.stat().st_mtime <= before_ts)

        if self.content:
            needle = self.content if self.case_sensitive else self.content.lower()
            predicates.append(lambda p: _contains_text(p, needle, self.case_sensitive))

        if self.file_hash:
            wanted_hash = self.file_hash.lower()
            predicates.append(lambda p: _safe_hash(p) == wanted_hash)

        if not predicates:
            raise OperationError("At least one search criterion must be provided.")
        return predicates


def _contains_text(path: Path, needle: str, case_sensitive: bool) -> bool:
    """Stream a file looking for *needle*; binary/unreadable files never match."""
    try:
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            while True:
                chunk = handle.read(_CONTENT_CHUNK)
                if not chunk:
                    return False
                hay = chunk if case_sensitive else chunk.lower()
                if needle in hay:
                    return True
    except (OSError, UnicodeDecodeError):
        return False


def _safe_hash(path: Path) -> str:
    try:
        return hash_file(path)
    except OperationError:
        return ""


def search(
    root: str | Path,
    criteria: SearchCriteria,
    *,
    recursive: bool = True,
    skip_hidden: bool = False,
    limit: int | None = None,
) -> OperationResult:
    """Search *root* and return matching files as an operation result."""
    base = validate_path(root, must_exist=True)
    predicates = criteria.build()
    result = OperationResult(operation="search")

    for file_path in iter_files(base, recursive=recursive, skip_hidden=skip_hidden):
        try:
            if all(predicate(file_path) for predicate in predicates):
                size = file_path.stat().st_size
                result.add(Action(kind="match", source=str(file_path), size=size))
                if limit is not None and result.items >= limit:
                    break
        except OSError as exc:
            result.error(f"{file_path}: {exc}")

    logger.info("Search found %d match(es) (%s)", result.items, human_readable_size(result.bytes))
    return result.finish()
