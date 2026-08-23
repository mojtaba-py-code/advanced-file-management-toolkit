# Contributing

Thanks for taking the time to contribute.

## Getting set up

```bash
git clone https://github.com/mojtaba-py-code/advanced-file-management-toolkit.git
cd advanced-file-management-toolkit
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate
pip install -r requirements-dev.txt
pip install ruff mypy bandit pip-audit
```

## Before opening a pull request

Run everything CI runs:

```bash
pytest --cov=core --cov=utils --cov=database --cov-report=term-missing
ruff check .
ruff format --check .
mypy core utils database main.py
bandit -r core utils database main.py -ll
```

All of these must pass. CI runs the test suite on Linux, macOS and Windows
against Python 3.12 and 3.13.

## Working on this codebase

**Route path handling through `utils/security.py`.** The security guarantees only
hold because every path-touching operation goes through the same helpers. If you
add an operation that writes, moves or deletes, call
`validate_path(..., for_write=True)` at the entry point — a guard that only some
call sites use is not a guard.

**Test both platforms' path rules.** The deny-list behaves differently on POSIX
and Windows, and a bug in one is easy to miss while developing on the other. See
`tests/test_protected_locations.py` for the pattern: use `PurePosixPath` and
`PureWindowsPath` so a regression on either platform is caught everywhere.

**Every destructive operation needs a dry run.** New commands that modify the
filesystem must support `--dry-run` and honour confirmation via `--force`.

**Keep the result model uniform.** Core operations return an `OperationResult`
built from `Action` records (`core/base.py`), which is what makes reporting,
history and the CLI work the same way for every command.

## Commit messages

Write in the imperative mood and explain *why* in the body when it is not
obvious from the diff:

```
Enforce the deny-list in every destructive entry point

clean(), batch_rename() and resolve_duplicates() validated their root
without for_write=True, so the protected-location check never ran for the
three operations most able to damage a system.
```

## Reporting bugs

Open an issue with your OS, Python version, the exact command, and what you
expected versus what happened. For anything security-sensitive, follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.
