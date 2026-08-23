"""Filesystem helper utilities shared across core modules."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Mapping of high-level categories to file extensions. Used by the organizer
# and the disk-usage analyzer. Extensions are stored lowercase, without a dot.
FILE_TYPE_MAP: dict[str, tuple[str, ...]] = {
    "Images": ("jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "svg", "heic", "ico"),
    "Videos": ("mp4", "mkv", "mov", "avi", "wmv", "flv", "webm", "m4v", "mpeg"),
    "Audio": ("mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus"),
    "Documents": ("pdf", "doc", "docx", "txt", "rtf", "odt", "md", "tex"),
    "Spreadsheets": ("xls", "xlsx", "csv", "tsv", "ods"),
    "Presentations": ("ppt", "pptx", "odp", "key"),
    "Archives": ("zip", "tar", "gz", "bz2", "xz", "7z", "rar", "tgz"),
    "Code": (
        "py",
        "js",
        "ts",
        "java",
        "c",
        "cpp",
        "cs",
        "go",
        "rs",
        "rb",
        "php",
        "html",
        "css",
        "json",
        "yaml",
        "yml",
        "sh",
        "sql",
    ),
    "Executables": ("exe", "msi", "bat", "cmd", "app", "deb", "rpm", "dmg"),
    "Fonts": ("ttf", "otf", "woff", "woff2"),
}

_EXTENSION_TO_CATEGORY: dict[str, str] = {
    ext: category for category, exts in FILE_TYPE_MAP.items() for ext in exts
}

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


@dataclass(frozen=True)
class FileInfo:
    """Lightweight, immutable snapshot of a file's metadata."""

    path: Path
    size: int
    created: datetime
    modified: datetime
    extension: str
    category: str


def human_readable_size(num_bytes: int, *, precision: int = 2) -> str:
    """Convert a byte count into a human-friendly string (e.g. ``1.50 MB``)."""
    if num_bytes < 0:
        raise ValueError("Byte count cannot be negative")
    size = float(num_bytes)
    for unit in _SIZE_UNITS:
        if size < 1024 or unit == _SIZE_UNITS[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    # Unreachable, but keeps type checkers satisfied.
    return f"{size:.{precision}f} {_SIZE_UNITS[-1]}"


def extension_of(path: Path) -> str:
    """Return the lowercase extension without the leading dot ("" if none)."""
    return path.suffix.lower().lstrip(".")


def categorize(path: Path) -> str:
    """Return the high-level category for *path* (``"Others"`` if unknown)."""
    return _EXTENSION_TO_CATEGORY.get(extension_of(path), "Others")


def _to_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=UTC)


def file_info(path: Path) -> FileInfo:
    """Build a :class:`FileInfo` snapshot for *path*."""
    stat = path.stat()
    return FileInfo(
        path=path,
        size=stat.st_size,
        created=_to_datetime(getattr(stat, "st_ctime", stat.st_mtime)),
        modified=_to_datetime(stat.st_mtime),
        extension=extension_of(path),
        category=categorize(path),
    )


def ensure_directory(path: Path) -> Path:
    """Create *path* (and parents) if missing and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_empty_dir(path: Path) -> bool:
    """Return ``True`` when *path* is a directory containing no entries."""
    if not path.is_dir():
        return False
    with os.scandir(path) as it:
        return next(it, None) is None
