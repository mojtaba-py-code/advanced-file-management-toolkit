## What this changes

<!-- A short description, and the issue it closes if there is one. -->

## Why

<!-- The reasoning that is not obvious from the diff. -->

## Checklist

- [ ] `pytest` passes
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `mypy core utils database main.py` passes
- [ ] New or changed behaviour is covered by tests
- [ ] Any operation that writes, moves or deletes calls `validate_path(..., for_write=True)` at its entry point
- [ ] Any new destructive operation supports `--dry-run` and honours `--force`
- [ ] `CHANGELOG.md` updated if this is user-visible
