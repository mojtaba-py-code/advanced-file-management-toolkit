# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-23

First public release.

### Added

- 15 file-management commands: organize, deduplicate, sync, backup, restore,
  search, batch rename, archive, extract, checksum, verify, analyze, clean,
  monitor and scheduled runs.
- Centralised path-security layer (`utils/security.py`) covering path
  resolution, traversal defence, zip-slip protection, symlink refusal and a
  protected-location deny-list.
- Full / incremental / differential backups with manifest-based verification.
- SQLite-backed operation history and JSON / CSV / TXT / HTML reporting.
- Layered YAML configuration with a `security.allowed_roots` allow-list.
- 144 tests at 90% coverage, including adversarial cases.
- CI across Linux, macOS and Windows on Python 3.12 and 3.13, with ruff, mypy,
  bandit, pip-audit and a full-history secret scan.

### Fixed

- The POSIX deny-list included `/` as a protected *subtree*, which marked every
  absolute path protected and made all write operations fail on Linux and macOS.
  A filesystem root is now an exact match only.
- `clean()`, `batch_rename()` and `resolve_duplicates()` validated their target
  without `for_write=True`, so the protected-location check never ran for the
  three operations most able to damage a system.
- `backups/` was ignored wholesale in `.gitignore`, so the directory was missing
  from a fresh clone.
- `security.allowed_roots` was documented as confining every operation, but no
  code path read it — setting it did nothing at all. It is now applied at
  startup and enforced inside `validate_path`. `require_confirmation` and
  `protect_system_paths` were dead config too; both behaviours are always on,
  so the keys were removed rather than left implying they could be turned off.
- The deny-list refused the OS scratch directory on macOS, where per-user temp
  directories live under `/var/folders` and `/var` is a protected subtree. The
  temp root is now exempt, which made every write operation unusable there.
- `resolve_path()` let a raw `ValueError` escape on Linux and macOS. A NUL byte
  in a path raises `OSError` on Windows but `ValueError` on POSIX, so callers
  catching `PathValidationError` — the whole point of the wrapper — missed it.

[1.0.0]: https://github.com/mojtaba-py-code/advanced-file-management-toolkit/releases/tag/v1.0.0
