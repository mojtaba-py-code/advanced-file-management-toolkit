"""Tests that the ``security.allowed_roots`` confinement policy is real.

This exists because the setting was documented in the README and in
SECURITY.md as the strongest control the toolkit offers, while no code path
actually consulted it. A security control that is documented but not wired up
is worse than none, because it is relied upon. These tests drive the policy
through the public CLI so it cannot silently become decorative again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from utils import security
from utils.exceptions import SecurityError
from utils.security import get_allowed_roots, set_allowed_roots, validate_path


@pytest.fixture(autouse=True)
def _reset_policy():
    """The policy is module state, so it must not leak between tests."""
    set_allowed_roots(None)
    yield
    set_allowed_roots(None)


# ---------------------------------------------------------------------------
# The policy itself
# ---------------------------------------------------------------------------
def test_policy_is_empty_by_default() -> None:
    assert get_allowed_roots() == ()


def test_setting_roots_confines_validation(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    set_allowed_roots([allowed])
    assert validate_path(allowed / "file.txt", must_exist=False) == (allowed / "file.txt").resolve()
    with pytest.raises(SecurityError):
        validate_path(outside / "file.txt", must_exist=False)


def test_clearing_the_policy_restores_unrestricted_access(tmp_path: Path) -> None:
    set_allowed_roots([tmp_path / "allowed"])
    set_allowed_roots(None)
    assert get_allowed_roots() == ()
    assert validate_path(tmp_path, must_exist=True)


@pytest.mark.parametrize("raised", [OSError, ValueError, RuntimeError])
def test_an_unresolvable_root_is_rejected_not_ignored(raised, monkeypatch) -> None:
    """A bad entry in the confinement list must fail loudly, never widen access.

    The failure is forced rather than fed a platform-specific bad path: which
    inputs are unresolvable differs by OS and by Python version (3.13 on Windows
    tolerates a NUL byte that 3.12 rejects), and the contract under test is
    "whatever cannot be resolved is refused", not "this string is invalid here".
    """

    def boom(self, strict=False):
        raise raised("cannot resolve")

    monkeypatch.setattr(Path, "resolve", boom)
    with pytest.raises(SecurityError):
        set_allowed_roots(["some-root"])
    # And the policy must not have been left half-applied.
    monkeypatch.undo()
    assert get_allowed_roots() == ()


def test_explicit_argument_overrides_the_policy(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    set_allowed_roots([a])
    # An explicit allow-list is honoured over the ambient policy.
    assert validate_path(b, must_exist=True, allowed_roots=[b]) == b.resolve()


def test_traversal_cannot_escape_the_policy(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    set_allowed_roots([allowed])
    with pytest.raises(SecurityError):
        validate_path(allowed / ".." / "escaped.txt", must_exist=False)


# ---------------------------------------------------------------------------
# End to end, through the CLI — the part that was actually broken
# ---------------------------------------------------------------------------
def _config_confined_to(tmp_path: Path, root: Path) -> Path:
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        "security:\n  allowed_roots:\n    - " + str(root).replace("\\", "/") + "\n",
        encoding="utf-8",
    )
    return cfg


def test_cli_refuses_a_target_outside_the_configured_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (outside / "a.txt").write_text("x", encoding="utf-8")

    cfg = _config_confined_to(tmp_path, allowed)
    exit_code = main.main(["organize", str(outside), "--dry-run", "--config", str(cfg)])
    assert exit_code == 2, "an out-of-bounds target must be refused, not organized"


def test_cli_allows_a_target_inside_the_configured_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "a.txt").write_text("x", encoding="utf-8")

    cfg = _config_confined_to(tmp_path, allowed)
    assert main.main(["organize", str(allowed), "--dry-run", "--config", str(cfg)]) == 0


def test_cli_is_unrestricted_when_no_roots_are_configured(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")

    cfg = tmp_path / "settings.yaml"
    cfg.write_text("security:\n  allowed_roots: []\n", encoding="utf-8")
    assert main.main(["organize", str(src), "--dry-run", "--config", str(cfg)]) == 0
    assert security.get_allowed_roots() == ()
