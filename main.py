#!/usr/bin/env python3
"""Advanced File Management Toolkit — command-line entry point.

A single, professional CLI that exposes every feature of the toolkit as a
sub-command. Global behaviour (dry-run, recursion, threads, reporting) is
controlled with shared flags, and a YAML config file supplies the defaults.

Run ``python main.py --help`` or ``python main.py <command> --help`` for usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the project root is importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import (
    analyzer,
    archive,
    backup,
    batch,
    checksum,
    cleaner,
    duplicate,
    monitor,
    organizer,
    scheduler,
    search,
    sync,
)
from core.base import OperationResult
from core.cli_helpers import (
    error,
    info,
    maybe_report,
    parse_date,
    parse_size,
    print_result,
    record_history,
    success,
    warn,
)
from database.history import HistoryDB
from utils import security
from utils.config import Config
from utils.exceptions import OperationError, ToolkitError
from utils.logging_config import setup_logging

PROJECT_ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def _common_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="FILE", help="Path to a YAML config file.")
    common.add_argument("--dry-run", action="store_true", help="Preview actions without changing anything.")
    common.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Recurse into sub-directories.",
    )
    common.add_argument("--threads", type=int, help="Worker threads (reserved for parallel scans).")
    common.add_argument("--force", action="store_true", help="Skip confirmation prompts (dangerous).")
    common.add_argument("--verbose", "-v", action="store_true", help="Verbose (DEBUG) logging.")
    common.add_argument("--output", "-o", metavar="PATH", help="Write a report to this path/dir.")
    common.add_argument(
        "--format", dest="fmt", choices=("json", "csv", "txt", "html"), default="json", help="Report format."
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common_parser()
    parser = argparse.ArgumentParser(
        prog="aftk",
        description="Advanced File Management Toolkit — automate advanced file tasks safely.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="Advanced File Management Toolkit 1.0.0")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # organize -------------------------------------------------------------
    p = sub.add_parser("organize", parents=[common], help="Organize files into sub-folders.")
    p.add_argument("source", help="Directory to organize.")
    p.add_argument("--strategy", choices=list(organizer.STRATEGIES), default="category")

    # duplicates -----------------------------------------------------------
    p = sub.add_parser("duplicates", parents=[common], help="Find (and optionally resolve) duplicate files.")
    p.add_argument("root", help="Directory to scan.")
    p.add_argument("--action", choices=("report", "move", "delete"), default="report")
    p.add_argument("--move-to", help="Destination folder when --action move.")

    # sync -----------------------------------------------------------------
    p = sub.add_parser("sync", parents=[common], help="Synchronise two directories.")
    p.add_argument("source")
    p.add_argument("destination")
    p.add_argument("--mode", choices=("one-way", "mirror", "two-way"), default="one-way")

    # backup ---------------------------------------------------------------
    p = sub.add_parser("backup", parents=[common], help="Create a backup.")
    p.add_argument("source")
    p.add_argument("--dest", help="Backup destination (defaults to config).")
    p.add_argument(
        "--type", dest="backup_type", choices=("full", "incremental", "differential"), default="full"
    )
    p.add_argument("--no-compression", action="store_true")
    p.add_argument("--no-verify", action="store_true")

    # restore --------------------------------------------------------------
    p = sub.add_parser("restore", parents=[common], help="Restore files from a backup.")
    p.add_argument("backup", help="Backup directory or .zip.")
    p.add_argument("target", help="Where to restore files.")

    # backups (list) -------------------------------------------------------
    p = sub.add_parser("backups", parents=[common], help="List existing backups.")
    p.add_argument("--dest", help="Backup destination (defaults to config).")

    # search ---------------------------------------------------------------
    p = sub.add_parser("search", parents=[common], help="Search for files.")
    p.add_argument("root")
    p.add_argument("--name", help="Glob pattern, e.g. '*.log'.")
    p.add_argument("--regex", help="Regex matched against file name.")
    p.add_argument("--ext", help="File extension, e.g. pdf.")
    p.add_argument("--min-size", help="Minimum size, e.g. 10MB.")
    p.add_argument("--max-size", help="Maximum size, e.g. 1GB.")
    p.add_argument("--after", help="Modified after YYYY-MM-DD.")
    p.add_argument("--before", help="Modified before YYYY-MM-DD.")
    p.add_argument("--content", help="Substring to find inside text files.")
    p.add_argument("--hash", dest="file_hash", help="Exact SHA-256 to match.")
    p.add_argument("--limit", type=int, help="Stop after N matches.")
    p.add_argument("--case-sensitive", action="store_true")

    # rename ---------------------------------------------------------------
    p = sub.add_parser("rename", parents=[common], help="Batch rename files (preview by default).")
    p.add_argument("root")
    p.add_argument("--prefix", default="")
    p.add_argument("--suffix", default="")
    p.add_argument("--replace", help="literal replacement as FROM:TO")
    p.add_argument("--regex", help="regex replacement as PATTERN:REPL")
    p.add_argument("--number", action="store_true", help="Append a sequential number.")
    p.add_argument("--case", choices=("lower", "upper", "title", "capitalize"))

    # archive --------------------------------------------------------------
    p = sub.add_parser("archive", parents=[common], help="Create a ZIP/TAR archive.")
    p.add_argument("source")
    p.add_argument("output")
    p.add_argument(
        "--archive-format", dest="arc_fmt", choices=("zip", "tar", "tar.gz", "tgz", "tar.bz2"), default="zip"
    )

    # extract --------------------------------------------------------------
    p = sub.add_parser("extract", parents=[common], help="Safely extract an archive.")
    p.add_argument("archive")
    p.add_argument("output")
    p.add_argument(
        "--max-size",
        type=_optional_size,
        default=archive.DEFAULT_MAX_EXTRACT_BYTES,
        metavar="SIZE",
        help=(
            "Ceiling on total expanded output, e.g. 500MB (default: 2GB). "
            "Guards against decompression bombs. Use 'none' to lift it."
        ),
    )
    p.add_argument(
        "--max-ratio",
        type=_optional_ratio,
        default=archive.DEFAULT_MAX_COMPRESSION_RATIO,
        metavar="N",
        help=(
            "Refuse an archive declaring more than N:1 expansion "
            f"(default: {archive.DEFAULT_MAX_COMPRESSION_RATIO}). Use 'none' to lift it."
        ),
    )

    # clean ----------------------------------------------------------------
    p = sub.add_parser("clean", parents=[common], help="Remove empty folders, zero-byte and temp files.")
    p.add_argument("root")
    p.add_argument("--no-empty", action="store_true")
    p.add_argument("--no-zero", action="store_true")
    p.add_argument("--no-temp", action="store_true")

    # analyze --------------------------------------------------------------
    p = sub.add_parser("analyze", parents=[common], help="Disk usage analysis.")
    p.add_argument("root")
    p.add_argument("--top", type=int, default=10)

    # monitor --------------------------------------------------------------
    p = sub.add_parser("monitor", parents=[common], help="Watch a folder for changes in real time.")
    p.add_argument("path")
    p.add_argument("--duration", type=float, help="Seconds to watch (default: until Ctrl-C).")

    # checksum -------------------------------------------------------------
    p = sub.add_parser("checksum", parents=[common], help="Generate a hash manifest.")
    p.add_argument("path")
    p.add_argument("--algorithm", choices=("sha256", "sha1", "md5"), default="sha256")

    # verify ---------------------------------------------------------------
    p = sub.add_parser("verify", parents=[common], help="Verify files against a manifest JSON.")
    p.add_argument("manifest", help="Manifest JSON produced by 'checksum -o'.")
    p.add_argument("root", help="Directory the manifest paths are relative to.")

    # history --------------------------------------------------------------
    p = sub.add_parser("history", parents=[common], help="Show recorded operation history.")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--stats", action="store_true")
    p.add_argument("--clear", action="store_true")

    # schedule -------------------------------------------------------------
    p = sub.add_parser("schedule", parents=[common], help="Run a maintenance job on a recurring schedule.")
    p.add_argument("job", choices=("backup", "clean", "organize", "sync"))
    p.add_argument("path")
    p.add_argument("--destination", help="Destination (required for sync; backup dest otherwise).")
    p.add_argument("--every", type=int, default=1, help="Interval count.")
    p.add_argument("--unit", choices=("minutes", "hours", "days"), default="hours")
    p.add_argument("--at", help="HH:MM for daily jobs.")
    p.add_argument("--run-once", action="store_true", help="Run once immediately, then exit.")
    p.add_argument("--strategy", default="category", help="Organizer strategy (job=organize).")
    p.add_argument("--mode", default="one-way", help="Sync mode (job=sync).")
    p.add_argument(
        "--backup-type", dest="sched_backup_type", default="full", help="Backup type (job=backup)."
    )

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
def _optional_size(value: str) -> int | None:
    """Parse a size limit, where the literal ``none`` lifts the limit."""
    if value.strip().lower() == "none":
        return None
    return parse_size(value)


def _optional_ratio(value: str) -> int | None:
    """Parse a ratio limit, where the literal ``none`` lifts the limit."""
    if value.strip().lower() == "none":
        return None
    return int(value)


def _resolve_recursive(args: argparse.Namespace, cfg: Config) -> bool:
    if args.recursive is not None:
        return args.recursive
    return bool(cfg.get("general.recursive", True))


def cmd_organize(args, cfg, db) -> OperationResult:
    return organizer.organize(
        args.source,
        strategy=args.strategy,
        recursive=_resolve_recursive(args, cfg),
        dry_run=args.dry_run,
        skip_hidden=bool(cfg.get("general.skip_hidden", False)),
    )


def cmd_duplicates(args, cfg, db) -> OperationResult:
    return duplicate.resolve_duplicates(
        args.root,
        action=args.action,
        move_to=args.move_to,
        recursive=_resolve_recursive(args, cfg),
        algorithm=cfg.get("hashing.algorithm", "sha256"),
        dry_run=args.dry_run,
        force=args.force,
    )


def cmd_sync(args, cfg, db) -> OperationResult:
    return sync.sync(args.source, args.destination, mode=args.mode, dry_run=args.dry_run, force=args.force)


def cmd_backup(args, cfg, db) -> OperationResult:
    dest = args.dest or cfg.get("backup.destination", "backups")
    return backup.create_backup(
        args.source,
        dest,
        backup_type=args.backup_type,
        compression=not args.no_compression and bool(cfg.get("backup.compression", True)),
        verify=not args.no_verify and bool(cfg.get("backup.verify", True)),
        dry_run=args.dry_run,
    )


def cmd_restore(args, cfg, db) -> OperationResult:
    return backup.restore_backup(args.backup, args.target, dry_run=args.dry_run)


def cmd_backups(args, cfg, db) -> None:
    dest = args.dest or cfg.get("backup.destination", "backups")
    entries = backup.list_backups(dest)
    if not entries:
        info("No backups found.")
        return
    for item in entries:
        info(f"  {item['timestamp']}  {item['type']:<12} {item['files']} file(s)  [{item['name']}]")


def cmd_search(args, cfg, db) -> OperationResult:
    criteria = search.SearchCriteria(
        name=args.name,
        regex=args.regex,
        extension=args.ext,
        min_size=parse_size(args.min_size) if args.min_size else None,
        max_size=parse_size(args.max_size) if args.max_size else None,
        modified_after=parse_date(args.after) if args.after else None,
        modified_before=parse_date(args.before) if args.before else None,
        content=args.content,
        file_hash=args.file_hash,
        case_sensitive=args.case_sensitive,
    )
    return search.search(args.root, criteria, recursive=_resolve_recursive(args, cfg), limit=args.limit)


def cmd_rename(args, cfg, db) -> OperationResult:
    replace_from, replace_to = [*args.replace.split(":", 1), ""][:2] if args.replace else (None, "")
    regex_from, regex_to = [*args.regex.split(":", 1), ""][:2] if args.regex else (None, "")
    rules = batch.RenameRules(
        prefix=args.prefix,
        suffix=args.suffix,
        replace_from=replace_from,
        replace_to=replace_to,
        regex_from=regex_from,
        regex_to=regex_to,
        number=args.number,
        case=args.case,
    )
    # Rename previews unless the user explicitly disables dry-run with --no-... ;
    # here we treat --dry-run as the safe default hint but honour the flag.
    return batch.batch_rename(args.root, rules, recursive=_resolve_recursive(args, cfg), dry_run=args.dry_run)


def cmd_archive(args, cfg, db) -> OperationResult:
    return archive.create_archive(args.source, args.output, fmt=args.arc_fmt, dry_run=args.dry_run)


def cmd_extract(args, cfg, db) -> OperationResult:
    return archive.extract_archive(
        args.archive,
        args.output,
        dry_run=args.dry_run,
        max_bytes=args.max_size,
        max_ratio=args.max_ratio,
    )


def cmd_clean(args, cfg, db) -> OperationResult:
    return cleaner.clean(
        args.root,
        empty_dirs=not args.no_empty,
        zero_byte=not args.no_zero,
        temp_files=not args.no_temp,
        recursive=_resolve_recursive(args, cfg),
        dry_run=args.dry_run,
        force=args.force,
    )


def cmd_analyze(args, cfg, db) -> OperationResult:
    return analyzer.analyze(args.root, top=args.top, recursive=_resolve_recursive(args, cfg))


def cmd_monitor(args, cfg, db) -> None:
    count = monitor.monitor(args.path, recursive=_resolve_recursive(args, cfg), duration=args.duration)
    success(f"Observed {count} event(s).")


def cmd_checksum(args, cfg, db) -> OperationResult:
    return checksum.generate_manifest(
        args.path,
        algorithm=args.algorithm,
        recursive=_resolve_recursive(args, cfg),
        chunk_size=int(cfg.get("hashing.chunk_size", 1048576)),
    )


def cmd_verify(args, cfg, db) -> OperationResult:
    manifest_data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    # Accept both a raw {path: hash} map and a full report payload.
    manifest = manifest_data.get("summary", {}).get("manifest") if isinstance(manifest_data, dict) else None
    if manifest is None:
        manifest = (
            manifest_data.get("manifest", manifest_data) if isinstance(manifest_data, dict) else manifest_data
        )
    return checksum.verify_manifest(args.root, manifest, algorithm=cfg.get("hashing.algorithm", "sha256"))


def cmd_history(args, cfg, db) -> None:
    if args.clear:
        removed = db.clear()
        success(f"Cleared {removed} history record(s).")
        return
    if args.stats:
        stats = db.stats()
        info(json.dumps(stats, indent=2))
        return
    records = db.recent(limit=args.limit)
    if not records:
        info("No history yet.")
        return
    for rec in records:
        info(f"  {rec.timestamp}  {rec.operation:<12} {rec.status:<8} items={rec.items} bytes={rec.bytes}")


def cmd_schedule(args, cfg, db) -> None:
    """Schedule a maintenance job (backup/clean/organize/sync)."""
    if args.job == "backup":
        dest = args.destination or cfg.get("backup.destination", "backups")
        func = lambda: backup.create_backup(args.path, dest, backup_type=args.sched_backup_type)  # noqa: E731
    elif args.job == "clean":
        func = lambda: cleaner.clean(args.path, force=True)  # noqa: E731
    elif args.job == "organize":
        func = lambda: organizer.organize(args.path, strategy=args.strategy)  # noqa: E731
    elif args.job == "sync":
        if not args.destination:
            raise OperationError("Scheduling a sync job requires --destination.")
        func = lambda: sync.sync(args.path, args.destination, mode=args.mode, force=True)  # noqa: E731
    else:  # pragma: no cover - argparse restricts choices
        raise OperationError(f"Unknown job '{args.job}'.")

    job = scheduler.ScheduledJob(name=args.job, func=func, interval=args.every, unit=args.unit, at=args.at)
    scheduler.run_scheduler([job], run_once=args.run_once)
    success(f"Scheduled job '{args.job}' completed." if args.run_once else "Scheduler stopped.")


_HANDLERS = {
    "organize": cmd_organize,
    "duplicates": cmd_duplicates,
    "sync": cmd_sync,
    "backup": cmd_backup,
    "restore": cmd_restore,
    "backups": cmd_backups,
    "search": cmd_search,
    "rename": cmd_rename,
    "archive": cmd_archive,
    "extract": cmd_extract,
    "clean": cmd_clean,
    "analyze": cmd_analyze,
    "monitor": cmd_monitor,
    "checksum": cmd_checksum,
    "verify": cmd_verify,
    "history": cmd_history,
    "schedule": cmd_schedule,
}

# Commands that return an OperationResult (so we can print/report/record it).
_RESULT_COMMANDS = {
    "organize",
    "duplicates",
    "sync",
    "backup",
    "restore",
    "search",
    "rename",
    "archive",
    "extract",
    "clean",
    "analyze",
    "checksum",
    "verify",
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    cfg = Config.load(getattr(args, "config", None))

    # Apply the confinement policy before any handler can touch the filesystem.
    try:
        security.set_allowed_roots(cfg.get("security.allowed_roots", []))
    except ToolkitError as exc:
        error(f"Error: {exc}")
        return 2

    log_cfg = dict(cfg.section("logging"))
    if getattr(args, "verbose", False):
        log_cfg["level"] = "DEBUG"
    setup_logging(log_cfg, root=PROJECT_ROOT)

    db: HistoryDB | None = None
    try:
        db = HistoryDB(PROJECT_ROOT / cfg.get("database.path", "database/history.db"))
    except Exception as exc:
        warn(f"History disabled: {exc}")

    handler = _HANDLERS[args.command]
    try:
        result = handler(args, cfg, db)
    except ToolkitError as exc:
        error(f"Error: {exc}")
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        warn("Interrupted.")
        return 130
    except Exception as exc:
        error(f"Unexpected error: {exc}")
        return 1

    if args.command in _RESULT_COMMANDS and isinstance(result, OperationResult):
        print_result(result)
        fmt = getattr(args, "fmt", "json")
        maybe_report(result, getattr(args, "output", None), fmt)
        record_history(db, result)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
