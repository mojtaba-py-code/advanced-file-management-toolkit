"""Disk-usage analyzer.

Produces storage statistics for a directory tree: total size, largest files,
largest immediate sub-folders and a breakdown by file category. The result is
report-ready so it can be exported to JSON/CSV/HTML.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from core.base import Action, OperationResult
from utils.fs import categorize, human_readable_size
from utils.logging_config import get_logger
from utils.security import iter_files, validate_path

logger = get_logger("analyzer")


def analyze(
    root: str | Path,
    *,
    top: int = 10,
    recursive: bool = True,
) -> OperationResult:
    """Analyse storage usage under *root*."""
    base = validate_path(root, must_exist=True)
    result = OperationResult(operation="analyze")

    total_bytes = 0
    file_count = 0
    by_category: dict[str, int] = defaultdict(int)
    by_category_count: dict[str, int] = defaultdict(int)
    by_subfolder: dict[str, int] = defaultdict(int)
    largest: list[tuple[Path, int]] = []

    for file_path in iter_files(base, recursive=recursive):
        try:
            size = file_path.stat().st_size
        except OSError as exc:
            result.error(f"{file_path}: {exc}")
            continue
        total_bytes += size
        file_count += 1

        category = categorize(file_path)
        by_category[category] += size
        by_category_count[category] += 1
        largest.append((file_path, size))

        # Attribute size to the top-level sub-folder under base.
        if base.is_dir():
            try:
                relative = file_path.relative_to(base)
                top_level = relative.parts[0] if len(relative.parts) > 1 else "(root)"
            except ValueError:
                top_level = "(root)"
            by_subfolder[top_level] += size

    largest.sort(key=lambda item: item[1], reverse=True)
    for path, size in largest[:top]:
        result.add(Action(kind="file", source=str(path), size=size, note=human_readable_size(size)))

    result.extra.update(
        {
            "total_bytes": total_bytes,
            "total_human": human_readable_size(total_bytes),
            "file_count": file_count,
            "by_category": {
                cat: {
                    "bytes": size,
                    "human": human_readable_size(size),
                    "count": by_category_count[cat],
                }
                for cat, size in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)
            },
            "largest_subfolders": [
                {"folder": folder, "bytes": size, "human": human_readable_size(size)}
                for folder, size in sorted(by_subfolder.items(), key=lambda kv: kv[1], reverse=True)[:top]
            ],
        }
    )

    logger.info(
        "Analyzed %s across %d file(s) under %s",
        human_readable_size(total_bytes),
        file_count,
        base,
    )
    return result.finish()
