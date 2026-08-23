"""Batch rename tool with a mandatory preview step.

Renames are computed first into a plan, checked for collisions, and only then
applied. Supported transformations: add prefix/suffix, sequential numbering,
literal text replacement, regex replacement and case conversion. Multiple
transformations can be combined in a single pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.base import Action, OperationResult
from utils.exceptions import OperationError
from utils.logging_config import get_logger
from utils.security import iter_files, validate_path

logger = get_logger("batch")

_CASE_MODES = ("lower", "upper", "title", "capitalize")


@dataclass
class RenameRules:
    """Declarative description of how filenames should be transformed."""

    prefix: str = ""
    suffix: str = ""  # inserted before the extension
    replace_from: str | None = None
    replace_to: str = ""
    regex_from: str | None = None
    regex_to: str = ""
    number: bool = False
    number_start: int = 1
    number_padding: int = 3
    case: str | None = None  # one of _CASE_MODES

    def validate(self) -> None:
        if self.case and self.case not in _CASE_MODES:
            raise OperationError(f"Unknown case mode '{self.case}'. Use {', '.join(_CASE_MODES)}.")
        if self.regex_from is not None:
            try:
                re.compile(self.regex_from)
            except re.error as exc:
                raise OperationError(f"Invalid regex '{self.regex_from}': {exc}") from exc
        if not any([self.prefix, self.suffix, self.replace_from, self.regex_from, self.number, self.case]):
            raise OperationError("No rename rule specified.")


def _apply_case(stem: str, mode: str) -> str:
    return {
        "lower": stem.lower(),
        "upper": stem.upper(),
        "title": stem.title(),
        "capitalize": stem.capitalize(),
    }[mode]


def _new_name(path: Path, rules: RenameRules, index: int) -> str:
    stem, ext = path.stem, path.suffix

    if rules.replace_from:
        stem = stem.replace(rules.replace_from, rules.replace_to)
    if rules.regex_from is not None:
        stem = re.sub(rules.regex_from, rules.regex_to, stem)
    if rules.case:
        stem = _apply_case(stem, rules.case)
    if rules.number:
        number = str(rules.number_start + index).zfill(rules.number_padding)
        stem = f"{stem}_{number}"

    stem = f"{rules.prefix}{stem}{rules.suffix}"
    return f"{stem}{ext}"


def plan_rename(
    root: str | Path,
    rules: RenameRules,
    *,
    recursive: bool = False,
    skip_hidden: bool = True,
) -> list[tuple[Path, Path]]:
    """Compute the ``(old, new)`` plan without touching the filesystem."""
    rules.validate()
    base = validate_path(root, must_exist=True)
    files = sorted(f for f in iter_files(base, recursive=recursive, skip_hidden=skip_hidden) if f.is_file())

    plan: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    for index, file_path in enumerate(files):
        new_name = _new_name(file_path, rules, index)
        new_path = file_path.with_name(new_name)
        if new_path == file_path:
            continue  # no change
        if new_path in seen or (new_path.exists() and new_path not in {p for p, _ in plan}):
            raise OperationError(
                f"Rename collision: multiple files map to {new_path.name}. Aborting for safety."
            )
        seen.add(new_path)
        plan.append((file_path, new_path))
    return plan


def batch_rename(
    root: str | Path,
    rules: RenameRules,
    *,
    recursive: bool = False,
    dry_run: bool = False,
    skip_hidden: bool = True,
) -> OperationResult:
    """Apply a batch rename. With ``dry_run=True`` this is the preview."""
    # Renaming rewrites the directory it runs in, so protected OS locations are
    # off-limits even for the preview.
    validate_path(root, must_exist=True, for_write=True)
    plan = plan_rename(root, rules, recursive=recursive, skip_hidden=skip_hidden)
    result = OperationResult(operation="rename", dry_run=dry_run)

    # Apply in an order that avoids transient collisions (rename to temp first
    # would be overkill here since plan_rename already guarantees uniqueness).
    for old_path, new_path in plan:
        try:
            if dry_run:
                result.add(
                    Action(kind="rename", source=str(old_path), destination=str(new_path), note="dry-run")
                )
                continue
            old_path.rename(new_path)
            result.add(Action(kind="rename", source=str(old_path), destination=str(new_path)))
        except OSError as exc:
            result.error(f"{old_path}: {exc}")
            logger.warning("Rename failed for %s: %s", old_path, exc)

    logger.info("%sRenamed %d file(s)", "[dry-run] " if dry_run else "", result.items)
    return result.finish()
