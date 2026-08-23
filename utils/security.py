"""Security primitives for safe filesystem operations.

This module is the security backbone of the toolkit. Every destructive or
path-touching operation is expected to route through the helpers here so that
the same guarantees apply everywhere:

* Paths are resolved and normalised before use (no ``..`` traversal surprises).
* Operations can be confined to an allow-listed set of root directories.
* A curated deny-list protects critical OS locations from modification.
* Symlinks are handled explicitly instead of being silently followed.
* Destructive actions require confirmation unless the caller opts out.

The design goal is "safe by default": a caller has to go out of their way to
do something dangerous.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from utils.exceptions import ConfirmationDeclined, PathValidationError, SecurityError

# ---------------------------------------------------------------------------
# Protected locations
# ---------------------------------------------------------------------------
# Directory *subtrees* that are never valid targets for destructive operations.
# The list is kept deliberately conservative and cross-platform: anything at or
# beneath one of these is refused.
#
# A filesystem root ("/" or a drive letter) is deliberately absent here. Every
# absolute path lives beneath a root, so treating one as a subtree would mark
# the whole disk protected; roots are handled as an exact match instead.
_WINDOWS_PROTECTED = (
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "C:\\ProgramData",
)
_POSIX_PROTECTED = (
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/proc",
    "/root",
    "/sbin",
    "/sys",
    "/usr",
    "/var",
)


def _protected_roots() -> tuple[Path, ...]:
    raw = _WINDOWS_PROTECTED if os.name == "nt" else _POSIX_PROTECTED
    roots: list[Path] = []
    for item in raw:
        try:
            roots.append(Path(item).resolve())
        except (OSError, RuntimeError):
            # A path we cannot resolve simply is not added to the list.
            continue
    return tuple(roots)


def resolve_path(path: str | os.PathLike[str], *, strict: bool = False) -> Path:
    """Return a fully-resolved, absolute :class:`~pathlib.Path`.

    ``strict=True`` requires the path to already exist (raises
    :class:`PathValidationError` otherwise). Resolution collapses ``..``
    segments and follows the real location on disk, which is what makes the
    traversal checks below reliable.
    """
    try:
        resolved = Path(path).expanduser().resolve(strict=strict)
    except FileNotFoundError as exc:
        raise PathValidationError(f"Path does not exist: {path}") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        # ValueError matters here: an embedded NUL byte raises OSError on
        # Windows but ValueError on POSIX, and either way the caller should
        # see this module's own exception type rather than a raw one.
        raise PathValidationError(f"Cannot resolve path: {path} ({exc})") from exc
    return resolved


def is_within(child: Path, parent: Path) -> bool:
    """Return ``True`` when *child* is *parent* itself or lives beneath it."""
    child = child.resolve()
    parent = parent.resolve()
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _temp_root() -> Path | None:
    """The OS-designated scratch directory, resolved, or ``None`` if unusable.

    This exists because macOS hands out per-user temp directories under
    ``/var/folders`` and resolves ``/var`` to ``/private/var``. Since ``/var``
    is a protected subtree on Unix, without this exemption the toolkit would
    refuse to operate in the very directory the OS provides for scratch work.
    """
    try:
        return Path(tempfile.gettempdir()).resolve()
    except (OSError, RuntimeError):  # pragma: no cover - platform dependent
        return None


def is_filesystem_root(path: Path) -> bool:
    r"""Return ``True`` when *path* is a filesystem root (``/`` or ``C:\``).

    Derived from the path itself rather than a hard-coded list, so it holds for
    every drive letter, UNC share and POSIX root alike.
    """
    resolved = path.resolve()
    return resolved.parent == resolved


def is_protected(path: Path) -> bool:
    r"""Return ``True`` when *path* is (or is inside) a protected OS location.

    Two distinct rules apply:

    * A filesystem root is protected as an **exact match only**. Wiping ``C:\``
      or ``/`` wholesale is refused, while the user's own files further down
      stay perfectly ordinary targets.
    * The curated OS directories are protected as **whole subtrees**, so a file
      inside ``C:\Windows`` or ``/etc`` is refused along with the directory.

    The OS scratch directory is exempt even when it falls inside one of those
    subtrees, which is what makes the toolkit usable under macOS's
    ``/var/folders``.
    """
    resolved = path.resolve()
    if is_filesystem_root(resolved):
        return True
    temp_root = _temp_root()
    if temp_root is not None and is_within(resolved, temp_root):
        # The scratch directory is user-writable by definition, even when it
        # happens to sit inside a protected subtree (as it does on macOS).
        return False
    # ``is_within`` already reports a directory as being within itself, so this
    # covers both the top of each subtree and everything beneath it.
    return any(is_within(resolved, root) for root in _protected_roots())


def validate_path(
    path: str | os.PathLike[str],
    *,
    must_exist: bool = True,
    allowed_roots: Sequence[str | os.PathLike[str]] | None = None,
    allow_symlink: bool = False,
    for_write: bool = False,
) -> Path:
    """Validate and resolve a user-supplied path.

    Parameters
    ----------
    path:
        The raw path to validate.
    must_exist:
        Require the path to exist on disk.
    allowed_roots:
        If provided, the resolved path must live inside one of these roots.
        This is the primary defence against directory-traversal attacks.
    allow_symlink:
        When ``False`` (default) a symlinked *path* is rejected. Following
        symlinks blindly is a classic way to escape an allowed root.
    for_write:
        When ``True``, additionally reject protected OS locations.

    Returns
    -------
    Path
        The safe, resolved path.
    """
    original = Path(path).expanduser()

    # Reject symlinks *before* resolving so we can detect them at all.
    if not allow_symlink and original.is_symlink():
        raise SecurityError(f"Refusing to operate on a symlink: {path}")

    resolved = resolve_path(path, strict=must_exist)

    if for_write and is_protected(resolved):
        raise SecurityError(f"Refusing to modify a protected system location: {resolved}")

    if allowed_roots:
        roots = [resolve_path(r, strict=False) for r in allowed_roots]
        if not any(is_within(resolved, root) for root in roots):
            raise SecurityError(
                f"Path {resolved} is outside the allowed root(s): {', '.join(str(r) for r in roots)}"
            )

    return resolved


def safe_join(base: str | os.PathLike[str], *parts: str) -> Path:
    """Join *parts* onto *base* and guarantee the result stays under *base*.

    This is the helper to use when composing a destination path from
    untrusted components (e.g. an archive member name), preventing the
    "zip-slip" class of vulnerability.
    """
    base_resolved = resolve_path(base, strict=False)
    candidate = base_resolved.joinpath(*parts).resolve()
    if not is_within(candidate, base_resolved):
        raise SecurityError(f"Refusing path traversal: {candidate} escapes {base_resolved}")
    return candidate


def confirm(prompt: str, *, force: bool = False, default: bool = False) -> bool:
    """Ask the user to confirm a destructive action.

    * ``force=True`` bypasses the prompt (for scripted/automated use).
    * When stdin is not interactive we fall back to *default* instead of
      blocking forever — but only ``force`` may approve destructive actions
      non-interactively, so *default* should stay ``False`` for deletes.
    """
    if force:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        return default
    suffix = " [y/N] " if not default else " [Y/n] "
    try:
        answer = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not answer:
        return default
    return answer in ("y", "yes")


def require_confirmation(prompt: str, *, force: bool = False) -> None:
    """Confirm a destructive action or raise :class:`ConfirmationDeclined`."""
    if not confirm(prompt, force=force, default=False):
        raise ConfirmationDeclined(f"Operation declined by user: {prompt}")


def unique_destination(destination: Path) -> Path:
    """Return a non-colliding variant of *destination*.

    Never overwrite silently: if ``report.txt`` exists we return
    ``report (1).txt``, then ``report (2).txt`` and so on.
    """
    if not destination.exists():
        return destination
    stem, suffix, parent = destination.stem, destination.suffix, destination.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def iter_files(
    root: Path,
    *,
    recursive: bool = True,
    follow_symlinks: bool = False,
    skip_hidden: bool = False,
) -> Iterable[Path]:
    """Yield files under *root* with symlink loops handled safely.

    ``os.walk`` is used with ``followlinks=False`` by default so a malicious
    or accidental symlink cycle cannot trap the walk in an infinite loop.
    """
    root = root.resolve()
    if root.is_file():
        yield root
        return
    for current, dirs, files in os.walk(root, followlinks=follow_symlinks):
        if skip_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if skip_hidden and name.startswith("."):
                continue
            candidate = Path(current) / name
            if not follow_symlinks and candidate.is_symlink():
                continue
            yield candidate
        if not recursive:
            break
