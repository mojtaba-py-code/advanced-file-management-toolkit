# Advanced File Management Toolkit

[![CI](https://github.com/mojtaba-py-code/advanced-file-management-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/mojtaba-py-code/advanced-file-management-toolkit/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat&logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/tests-144%20passing-brightgreen?style=flat)
![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen?style=flat)
![License](https://img.shields.io/badge/License-MIT-blue?style=flat)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat)

A **production-grade, security-first command-line toolkit** for automating advanced file-management
tasks — organizing, deduplicating, syncing, backing up, searching, monitoring and more — across
Windows, macOS and Linux.

Built around a *safe-by-default* philosophy: every destructive action supports **dry-run**, requires
**confirmation**, validates every path, and refuses to touch protected system locations.

---

## ✨ Features

| # | Feature | What it does |
|---|---------|--------------|
| 1 | **Smart Organizer** | Sort files into folders by category, extension, date or size (with custom rules) |
| 2 | **Duplicate Finder** | Two-phase (size → SHA-256) detection; report, move or delete duplicates |
| 3 | **Folder Sync** | One-way, mirror and two-way synchronisation with change detection |
| 4 | **Backup Engine** | Full / incremental / differential backups, compression, versioning & verification |
| 5 | **Restore** | Restore any backup (directory or `.zip`) with integrity checking |
| 6 | **Search Engine** | Find files by name, regex, extension, size, date, content or hash |
| 7 | **Batch Rename** | Prefix, suffix, numbering, replace, regex and case conversion — with preview |
| 8 | **Archive Manager** | Create/extract/verify ZIP & TAR archives (hardened against zip-slip) |
| 9 | **Integrity Checker** | SHA-256 / SHA-1 / MD5 manifests, streamed for huge files |
| 10 | **Disk Analyzer** | Storage stats: largest files, largest folders, breakdown by type |
| 11 | **Cleaner** | Remove empty folders, zero-byte files and temp files safely |
| 12 | **File Watcher** | Real-time folder monitoring (create/modify/delete/move) via `watchdog` |
| 13 | **Scheduler** | Run backups, cleanups, syncs and reports on a recurring schedule |
| 14 | **History (SQLite)** | Auditable record of every operation |
| 15 | **Reporting** | Export results to JSON / CSV / TXT / HTML |

Plus: rotating logs, coloured console output, a layered YAML configuration system, and full type hints.

---

## 🏗️ Architecture

```
advanced_file_toolkit/
├── main.py                 # CLI entry point (argparse) — wires commands to core
│
├── config/
│   ├── settings.yaml       # User-facing configuration (overrides built-in defaults)
│   └── logging.yaml        # Optional declarative logging config
│
├── core/                   # One module per feature — pure, testable logic
│   ├── base.py             # OperationResult / Action (uniform result model)
│   ├── organizer.py  duplicate.py  sync.py  backup.py  archive.py
│   ├── search.py     batch.py      cleaner.py  analyzer.py  monitor.py
│   ├── checksum.py   scheduler.py  cli_helpers.py
│
├── utils/                  # Cross-cutting concerns
│   ├── security.py         # Path validation, traversal defence, safe delete
│   ├── config.py           # Layered config loader (defaults + YAML merge)
│   ├── logging_config.py   # Rotating + coloured logging
│   ├── fs.py               # Filesystem helpers (sizes, categories, metadata)
│   ├── reporting.py        # JSON/CSV/TXT/HTML report generation
│   └── exceptions.py       # Typed exception hierarchy
│
├── database/
│   └── history.py          # SQLite-backed operation history
│
├── tests/                  # 144 tests · 90% coverage
├── logs/  reports/  backups/
│
├── .github/workflows/ci.yml    # tests on 3 OSes × 2 Python versions + lint, types, security
├── pyproject.toml              # packaging, ruff, mypy, pytest and coverage config
├── requirements.txt            requirements-dev.txt
└── README.md  SECURITY.md  CONTRIBUTING.md  CHANGELOG.md  LICENSE
```

**Design principles:** modular (SOLID), single uniform result object, security enforced in one place,
dependency-light (mostly the standard library), and everything covered by tests.

---

## 🚀 Installation

```bash
# 1. Clone
git clone https://github.com/mojtaba-py-code/advanced-file-management-toolkit.git
cd advanced-file-management-toolkit

# 2. (recommended) create a virtual environment
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (optional) install dev/test tooling
pip install -r requirements-dev.txt
```

Requires **Python 3.12+**.

---

## 💻 Usage

Every feature is a sub-command. Global flags (`--dry-run`, `--recursive/--no-recursive`, `--force`,
`--output`, `--format`, `--verbose`, `--config`) work across commands.

```bash
python main.py --help                 # list all commands
python main.py <command> --help       # detailed help for a command
```

### Examples

```bash
# Preview organizing Downloads by file type (nothing is moved)
python main.py organize ~/Downloads --strategy category --dry-run

# Find duplicates and export an HTML report (non-destructive)
python main.py duplicates ~/Pictures --action report -o report --format html

# Mirror a project folder to an external drive
python main.py sync ./project /mnt/backup/project --mode mirror

# Full, compressed, verified backup
python main.py backup ~/Documents --dest ./backups --type full

# Incremental backup (only what changed since the last backup)
python main.py backup ~/Documents --dest ./backups --type incremental

# Restore a backup
python main.py restore ./backups/2026-01-01_120000_full.zip ./restored

# Search: PDFs larger than 10MB modified this year, containing "invoice"
python main.py search ~/Documents --ext pdf --min-size 10MB --after 2026-01-01 --content invoice

# Batch rename (preview) — add prefix + sequential number
python main.py rename ./photos --prefix vacation_ --number --dry-run

# Create and verify an archive
python main.py archive ./logs ./logs.zip
python main.py extract ./logs.zip ./logs_restored

# Clean empty folders, zero-byte and temp files
python main.py clean ./workspace --dry-run

# Disk usage analysis
python main.py analyze ~/ --top 15 -o disk_report --format html

# Watch a folder live for 60 seconds
python main.py monitor ./inbox --duration 60

# Generate a hash manifest, then verify integrity later
python main.py checksum ./release -o manifest --format json
python main.py verify ./reports/manifest.json ./release

# Review what the toolkit has done
python main.py history --stats
```

---

## ⚙️ Configuration

All defaults live in `config/settings.yaml`. Anything you omit falls back to a safe built-in default,
and you can point at a different file with `--config path/to/file.yaml`.

```yaml
general:
  dry_run: false
  recursive: true
  threads: 4
security:
  allowed_roots: []          # confine ALL operations to these roots when set
hashing:
  algorithm: sha256
  chunk_size: 1048576        # streamed → memory-safe for huge files
```

---

## 🔒 Security

Security is a first-class concern, centralised in `utils/security.py`:

- **Path validation & resolution** — every path is resolved (collapsing `..`) before use.
- **Traversal / zip-slip defence** — archive members and composed paths are checked with `safe_join`;
  a crafted archive cannot write outside the target directory (covered by tests).
- **Confinement** — set `security.allowed_roots` to restrict every validated path to an
  explicit allow-list. Enforced in one place, applied before any command runs.
- **Protected locations** — refuses to modify OS/system directories (`C:\Windows`, `/etc`, …) or a
  filesystem root itself, and every destructive entry point enforces it.
- **No silent overwrites** — colliding writes are auto-renamed (`report (1).txt`).
- **Confirmation & dry-run** — destructive operations require `--force` or an interactive *yes*, and
  every one supports `--dry-run` to preview first.
- **Symlink safety** — symlinks are rejected by default and never followed during walks.
- **Integrity verification** — backups are re-hashed after writing to catch silent corruption.

The full threat model — including what the toolkit deliberately does *not* defend against —
is documented in [SECURITY.md](SECURITY.md), along with how to report a vulnerability privately.

---

## 🧪 Testing

```bash
pytest                                   # run the suite
pytest --cov=core --cov=utils --cov=database --cov-report=term-missing
```

**144 tests, 90% coverage**, including adversarial cases (zip-slip, path traversal, protected-location
refusal, rename collisions, integrity mismatch).

---

## 🤝 Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the local setup and the
checks CI runs. Release history lives in [CHANGELOG.md](CHANGELOG.md).

---

## 📄 License

Released under the [MIT License](LICENSE).
