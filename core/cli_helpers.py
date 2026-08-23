"""Presentation helpers shared by the CLI.

Keeps ``main.py`` focused on argument wiring by centralising result printing,
optional report writing and history recording.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.base import OperationResult
from database.history import HistoryDB, OperationRecord
from utils.fs import human_readable_size
from utils.reporting import generate_report

try:
    from rich.console import Console
    from rich.table import Table

    _console: Console | None = Console()
except ImportError:  # pragma: no cover - rich is optional
    _console = None


def info(message: str) -> None:
    if _console:
        _console.print(message)
    else:
        print(message)


def success(message: str) -> None:
    if _console:
        _console.print(f"[bold green]{message}[/bold green]")
    else:
        print(message)


def warn(message: str) -> None:
    if _console:
        _console.print(f"[bold yellow]{message}[/bold yellow]")
    else:
        print(message)


def error(message: str) -> None:
    if _console:
        _console.print(f"[bold red]{message}[/bold red]")
    else:
        print(message)


def print_result(result: OperationResult, *, show_actions: int = 20) -> None:
    """Render an :class:`OperationResult` to the terminal."""
    tag = "[dry-run] " if result.dry_run else ""
    header = f"{tag}{result.operation.title()}: {result.items} item(s), {human_readable_size(result.bytes)}"
    if result.errors:
        header += f", {len(result.errors)} error(s)"
    success(header)

    if _console and result.actions:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", justify="right")
        table.add_column("Action")
        table.add_column("Source", overflow="fold")
        table.add_column("Destination", overflow="fold")
        for index, action in enumerate(result.actions[:show_actions], start=1):
            table.add_row(str(index), action.kind, action.source, action.destination or "")
        _console.print(table)
        if len(result.actions) > show_actions:
            info(f"... and {len(result.actions) - show_actions} more (see report/log)")
    elif result.actions:
        for index, action in enumerate(result.actions[:show_actions], start=1):
            dest = f" -> {action.destination}" if action.destination else ""
            print(f"  {index}. [{action.kind}] {action.source}{dest}")

    for message in result.errors[:show_actions]:
        warn(f"  ! {message}")


def maybe_report(result: OperationResult, output: str | None, fmt: str) -> Path | None:
    """Write a report if the user asked for one via ``--output``."""
    if not output:
        return None
    path = generate_report(
        result.to_payload(),
        fmt=fmt,
        output_dir=Path(output).parent if Path(output).suffix else output,
        name=Path(output).stem if Path(output).suffix else None,
    )
    success(f"Report written: {path}")
    return path


def record_history(
    db: HistoryDB | None, result: OperationResult, *, source: str = "", destination: str = ""
) -> None:
    """Persist an operation to the history database (best-effort)."""
    if db is None:
        return
    try:
        db.record(
            OperationRecord(
                operation=result.operation,
                status="dry-run" if result.dry_run else ("error" if result.errors else "ok"),
                source=source or None,
                destination=destination or None,
                details=None,
                items=result.items,
                bytes=result.bytes,
                duration_ms=result.duration_ms,
            )
        )
    except Exception as exc:
        warn(f"Could not record history: {exc}")


def parse_size(value: str) -> int:
    """Parse a human size like ``10MB`` / ``500k`` / ``1024`` into bytes."""
    value = value.strip().upper()
    units = {"B": 1, "K": 1024, "KB": 1024, "M": 1024**2, "MB": 1024**2, "G": 1024**3, "GB": 1024**3}
    for suffix in sorted(units, key=len, reverse=True):
        if value.endswith(suffix):
            number = value[: -len(suffix)].strip()
            return int(float(number) * units[suffix])
    return int(value)


def parse_date(value: str) -> datetime:
    """Parse ``YYYY-MM-DD`` (or full ISO) into a :class:`datetime`."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD.")
