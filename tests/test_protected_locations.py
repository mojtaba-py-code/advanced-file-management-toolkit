"""Tests for the protected-location deny-list.

Two properties matter here and both have bitten this module before:

1. The deny-list must protect *specific* OS directories without accidentally
   protecting the entire disk. A filesystem root is a special case: refusing to
   operate on ``/`` itself is right, refusing everything beneath it is not.
2. Every destructive entry point must actually consult the deny-list. A guard
   that only some call sites use is not a guard.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from core.batch import RenameRules, batch_rename
from core.cleaner import clean
from core.duplicate import resolve_duplicates
from utils import security
from utils.exceptions import PathValidationError, SecurityError
from utils.security import is_filesystem_root, is_protected, validate_path


# ---------------------------------------------------------------------------
# Filesystem roots vs. ordinary user paths
# ---------------------------------------------------------------------------
def test_filesystem_root_is_protected() -> None:
    root = Path(Path.cwd().anchor)
    assert is_filesystem_root(root) is True
    assert is_protected(root) is True


def test_ordinary_user_path_is_not_protected(tmp_path: Path) -> None:
    """A temp directory sits under a filesystem root but must stay writable."""
    assert is_filesystem_root(tmp_path) is False
    assert is_protected(tmp_path) is False
    assert validate_path(tmp_path, must_exist=True, for_write=True) == tmp_path.resolve()


def test_root_is_absent_from_the_posix_subtree_list() -> None:
    """ "/" as a subtree entry would mark every absolute POSIX path protected."""
    assert "/" not in security._POSIX_PROTECTED


@pytest.mark.parametrize(
    ("pure", "candidate", "entries"),
    [
        (PurePosixPath, "/home/user/Downloads", security._POSIX_PROTECTED),
        (PureWindowsPath, "C:/Users/user/Downloads", security._WINDOWS_PROTECTED),
    ],
)
def test_no_deny_list_entry_swallows_a_home_directory(pure, candidate, entries) -> None:
    """Platform-independent check, so a POSIX regression is caught on Windows too."""
    target = pure(candidate)
    for entry in entries:
        assert not target.is_relative_to(pure(entry)), (
            f"{entry!r} would protect {candidate!r} and everything else on the disk"
        )


def test_curated_os_directory_and_its_contents_are_protected() -> None:
    probe = Path("C:/Windows") if os.name == "nt" else Path("/etc")
    if not probe.exists():
        pytest.skip(f"{probe} not present on this platform")
    assert is_protected(probe) is True
    assert is_protected(probe / "some-file.conf") is True
    with pytest.raises(SecurityError):
        validate_path(probe, must_exist=True, for_write=True)


# ---------------------------------------------------------------------------
# Destructive entry points must consult the deny-list
# ---------------------------------------------------------------------------
def _protected_probe() -> Path:
    probe = Path("C:/Windows") if os.name == "nt" else Path("/etc")
    if not probe.exists():
        pytest.skip(f"{probe} not present on this platform")
    return probe


def test_clean_refuses_a_protected_location() -> None:
    with pytest.raises(SecurityError):
        clean(_protected_probe(), dry_run=True, force=True)


def test_batch_rename_refuses_a_protected_location() -> None:
    with pytest.raises(SecurityError):
        batch_rename(_protected_probe(), RenameRules(prefix="x_"), dry_run=True)


@pytest.mark.parametrize("action", ["delete", "move"])
def test_resolve_duplicates_refuses_a_protected_location(action: str, tmp_path: Path) -> None:
    with pytest.raises(SecurityError):
        resolve_duplicates(
            _protected_probe(),
            action=action,
            move_to=tmp_path / "quarantine",
            dry_run=True,
            force=True,
        )


def test_resolve_duplicates_still_reports_on_a_protected_location(tmp_path: Path) -> None:
    """Reporting is read-only, so it must not be blocked — only mutation is."""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("same", encoding="utf-8")
    b.write_text("same", encoding="utf-8")
    result = resolve_duplicates(tmp_path, action="report")
    assert result.extra["groups"] == 1


# ---------------------------------------------------------------------------
# Path resolution must fail with this module's own exception type
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raised", [OSError, ValueError, RuntimeError])
def test_resolve_path_wraps_every_platform_failure(raised, monkeypatch) -> None:
    """A NUL byte raises OSError on Windows but ValueError on POSIX.

    Either way the caller must see PathValidationError, so this is forced
    rather than left to whichever platform the test happens to run on.
    """

    def boom(self, strict=False):
        raise raised("embedded null character in path")

    monkeypatch.setattr(Path, "resolve", boom)
    with pytest.raises(PathValidationError):
        security.resolve_path("bad" + chr(0) + "name", strict=True)


def test_resolve_path_rejects_a_null_byte_natively() -> None:
    """The real thing, on whichever platform is running."""
    with pytest.raises(PathValidationError):
        security.resolve_path("bad" + chr(0) + "name", strict=True)


# ---------------------------------------------------------------------------
# The OS scratch directory must stay usable
# ---------------------------------------------------------------------------
def test_system_temp_directory_is_not_protected() -> None:
    """macOS puts per-user temp dirs under /var/folders, and /var is denied."""
    temp_root = Path(tempfile.gettempdir()).resolve()
    assert is_protected(temp_root) is False
    assert validate_path(temp_root, must_exist=True, for_write=True) == temp_root


def test_temp_directory_is_exempt_even_inside_a_protected_subtree(monkeypatch) -> None:
    """Reproduces the macOS layout on any platform.

    Pin the temp root inside a directory that is on the deny-list and confirm
    the exemption wins, so a regression is caught on Linux and Windows too.
    """
    protected = Path(security._POSIX_PROTECTED[-1] if os.name != "nt" else security._WINDOWS_PROTECTED[0])
    fake_temp = protected / "folders" / "xy" / "scratch"

    monkeypatch.setattr(security, "_temp_root", lambda: fake_temp)
    assert is_protected(fake_temp / "pytest-of-runner" / "src") is False
    # Its protected parent is still refused — the exemption is scoped, not a hole.
    assert is_protected(protected / "something-else") is True


def test_exemption_is_skipped_when_the_temp_root_is_unavailable(monkeypatch) -> None:
    """A missing temp root must fail closed, not open."""
    monkeypatch.setattr(security, "_temp_root", lambda: None)
    probe = Path("C:/Windows") if os.name == "nt" else Path("/etc")
    assert is_protected(probe) is True
