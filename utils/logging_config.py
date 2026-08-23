"""Centralised logging configuration with rotation and optional colour.

A single :func:`setup_logging` call configures a rotating file handler plus a
console handler. Every module obtains its logger via :func:`get_logger`, so
the whole application shares consistent formatting and levels.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

try:
    from colorama import Fore, Style
    from colorama import init as colorama_init

    colorama_init()
    _COLOR = {
        "DEBUG": Fore.CYAN,
        "INFO": Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.MAGENTA + Style.BRIGHT,
    }
    _RESET = Style.RESET_ALL
except ImportError:  # pragma: no cover - colour is optional
    _COLOR = {}
    _RESET = ""

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

APP_LOGGER_NAME = "aftk"


class _ColorFormatter(logging.Formatter):
    """Formatter that colourises the level name for console output only."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        colour = _COLOR.get(record.levelname)
        if colour:
            return message.replace(record.levelname, f"{colour}{record.levelname}{_RESET}", 1)
        return message


def setup_logging(config: dict[str, Any] | None = None, *, root: Path | None = None) -> logging.Logger:
    """Configure and return the application logger.

    Parameters
    ----------
    config:
        The ``logging`` section of the toolkit configuration.
    root:
        Project root used to resolve the log directory (defaults to the
        package root).
    """
    config = config or {}
    root = root or Path(__file__).resolve().parent.parent

    level_name = str(config.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    log_dir = root / str(config.get("directory", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / str(config.get("file", "toolkit.log"))

    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    # Re-configuring should not stack duplicate handlers.
    logger.handlers.clear()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=int(config.get("max_bytes", 5_242_880)),
        backupCount=int(config.get("backup_count", 5)),
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    if config.get("console", True):
        console = logging.StreamHandler()
        console.setFormatter(_ColorFormatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        console.setLevel(level)
        logger.addHandler(console)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger of the application logger."""
    if name:
        return logging.getLogger(f"{APP_LOGGER_NAME}.{name}")
    return logging.getLogger(APP_LOGGER_NAME)
