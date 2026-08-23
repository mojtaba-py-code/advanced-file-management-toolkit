"""Real-time folder monitoring built on ``watchdog``.

Every filesystem event (create / modify / delete / move) is logged and, when a
history database is supplied, persisted. If ``watchdog`` is not installed the
module raises a clear, actionable error instead of failing obscurely.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from utils.exceptions import OperationError
from utils.logging_config import get_logger
from utils.security import validate_path

logger = get_logger("monitor")

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    _WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without watchdog
    _WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object  # type: ignore[assignment,misc]


EventCallback = Callable[[str, str], None]


class _LoggingHandler(FileSystemEventHandler):
    """Handler that logs each event and forwards it to an optional callback."""

    def __init__(self, callback: EventCallback | None = None) -> None:
        super().__init__()
        self.callback = callback
        self.event_count = 0

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory and event.event_type == "modified":
            # Directory "modified" events are noisy and rarely useful.
            return
        self.event_count += 1
        action = event.event_type.upper()
        raw = getattr(event, "dest_path", "") or event.src_path
        path = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
        logger.info("[WATCH] %-8s %s", action, path)
        if self.callback:
            try:
                self.callback(event.event_type, path)
            except Exception as exc:
                logger.error("Monitor callback error: %s", exc)


def monitor(
    path: str | Path,
    *,
    recursive: bool = True,
    duration: float | None = None,
    callback: EventCallback | None = None,
) -> int:
    """Watch *path* for changes.

    Parameters
    ----------
    duration:
        Seconds to watch before stopping. ``None`` watches until interrupted
        with Ctrl-C. Returns the number of events observed.
    """
    if not _WATCHDOG_AVAILABLE:
        raise OperationError(
            "The 'watchdog' package is required for monitoring. Install it with: pip install watchdog"
        )

    target = validate_path(path, must_exist=True)
    if not target.is_dir():
        raise OperationError(f"Monitor target must be a directory: {target}")

    handler = _LoggingHandler(callback)
    observer = Observer()
    observer.schedule(handler, str(target), recursive=recursive)
    observer.start()
    logger.info("Monitoring %s (recursive=%s). Press Ctrl-C to stop.", target, recursive)

    start = time.monotonic()
    try:
        while True:
            time.sleep(0.5)
            if duration is not None and (time.monotonic() - start) >= duration:
                break
    except KeyboardInterrupt:  # pragma: no cover - interactive path
        logger.info("Monitoring interrupted by user.")
    finally:
        observer.stop()
        observer.join()

    logger.info("Monitoring stopped after %d event(s).", handler.event_count)
    return handler.event_count
