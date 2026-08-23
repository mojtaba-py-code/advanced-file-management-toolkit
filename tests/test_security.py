"""Tests for the security primitives — the heart of the toolkit."""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.exceptions import ConfirmationDeclined, PathValidationError, SecurityError
from utils.security import (
    confirm,
    is_within,
    require_confirmation,
    safe_join,
    unique_destination,
    validate_path,
)


def test_validate_path_resolves_existing(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    assert validate_path(f) == f.resolve()


def test_validate_path_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(PathValidationError):
        validate_path(tmp_path / "nope.txt", must_exist=True)


def test_validate_path_enforces_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.txt").write_text("x", encoding="utf-8")

    # Inside the allowed root: fine.
    inside_file = allowed / "ok.txt"
    inside_file.write_text("x", encoding="utf-8")
    assert validate_path(inside_file, allowed_roots=[allowed])

    # Outside the allowed root: blocked.
    with pytest.raises(SecurityError):
        validate_path(outside / "x.txt", allowed_roots=[allowed])


def test_safe_join_blocks_traversal(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    # A normal join is allowed.
    assert safe_join(base, "sub", "file.txt") == (base / "sub" / "file.txt").resolve()
    # A traversal attempt is refused.
    with pytest.raises(SecurityError):
        safe_join(base, "..", "escape.txt")


def test_is_within(tmp_path: Path) -> None:
    parent = tmp_path / "p"
    child = parent / "c" / "d"
    parent.mkdir()
    assert is_within(child, parent) is True
    assert is_within(parent, child) is False


def test_unique_destination_avoids_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "report.txt"
    target.write_text("first", encoding="utf-8")
    alt = unique_destination(target)
    assert alt.name == "report (1).txt"
    assert not alt.exists()


def test_confirm_force_and_non_interactive() -> None:
    # force always approves.
    assert confirm("delete?", force=True) is True
    # Non-interactive (pytest captures stdin) falls back to default=False.
    assert confirm("delete?", default=False) is False


def test_require_confirmation_declines() -> None:
    with pytest.raises(ConfirmationDeclined):
        require_confirmation("delete everything?", force=False)
    # force bypasses.
    require_confirmation("delete everything?", force=True)
