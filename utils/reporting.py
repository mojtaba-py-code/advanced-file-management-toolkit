"""Multi-format report generation (JSON, CSV, TXT, HTML).

Reports are the user-facing summary of an operation. The generator accepts a
plain dictionary payload so any module can produce a report without coupling
to a specific structure.
"""

from __future__ import annotations

import csv
import html
import io
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from utils.exceptions import OperationError
from utils.fs import ensure_directory
from utils.security import unique_destination

SUPPORTED_FORMATS = ("json", "csv", "txt", "html")


def _timestamp_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort extraction of a tabular ``rows`` list from *payload*."""
    rows = payload.get("rows")
    if isinstance(rows, list) and all(isinstance(r, dict) for r in rows):
        return rows
    return []


def render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def render_csv(payload: dict[str, Any]) -> str:
    rows = _rows_from_payload(payload)
    buffer = io.StringIO()
    if not rows:
        # Fall back to a flat key/value dump of the summary section.
        writer = csv.writer(buffer)
        writer.writerow(["key", "value"])
        for key, value in payload.get("summary", payload).items():
            if not isinstance(value, (dict, list)):
                writer.writerow([key, value])
        return buffer.getvalue()

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    dict_writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    dict_writer.writeheader()
    for row in rows:
        dict_writer.writerow({key: row.get(key, "") for key in fieldnames})
    return buffer.getvalue()


def render_txt(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    title = payload.get("title", "Report")
    lines.append(title)
    lines.append("=" * len(title))
    lines.append(f"Generated: {payload.get('generated_at', datetime.now(UTC).isoformat())}")
    lines.append("")

    summary = payload.get("summary", {})
    if summary:
        lines.append("Summary")
        lines.append("-" * 7)
        for key, value in summary.items():
            lines.append(f"  {key}: {value}")
        lines.append("")

    rows = _rows_from_payload(payload)
    if rows:
        lines.append(f"Details ({len(rows)} rows)")
        lines.append("-" * 7)
        for index, row in enumerate(rows, start=1):
            rendered = ", ".join(f"{k}={v}" for k, v in row.items())
            lines.append(f"  {index}. {rendered}")
    return "\n".join(lines) + "\n"


def render_html(payload: dict[str, Any]) -> str:
    title = html.escape(str(payload.get("title", "Report")))
    generated = html.escape(str(payload.get("generated_at", datetime.now(UTC).isoformat())))

    summary_rows = "".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
        for k, v in payload.get("summary", {}).items()
    )

    rows = _rows_from_payload(payload)
    table_html = ""
    if rows:
        headers: list[str] = []
        for row in rows:
            for key in row:
                if key not in headers:
                    headers.append(key)
        head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(row.get(h, '')))}</td>" for h in headers) + "</tr>"
            for row in rows
        )
        table_html = f"<h2>Details</h2><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1f2937; }}
  h1 {{ color: #0e75b6; }}
  table {{ border-collapse: collapse; margin: 1rem 0; width: 100%; }}
  th, td {{ border: 1px solid #d1d5db; padding: 6px 10px; text-align: left; }}
  th {{ background: #f3f4f6; }}
  .meta {{ color: #6b7280; font-size: 0.9rem; }}
</style>
</head>
<body>
  <h1>{title}</h1>
  <p class="meta">Generated: {generated}</p>
  <h2>Summary</h2>
  <table>{summary_rows}</table>
  {table_html}
</body>
</html>
"""


_RENDERERS = {
    "json": render_json,
    "csv": render_csv,
    "txt": render_txt,
    "html": render_html,
}


def generate_report(
    payload: dict[str, Any],
    *,
    fmt: str = "json",
    output_dir: str | Path = "reports",
    name: str | None = None,
) -> Path:
    """Render *payload* to disk in *fmt* and return the written path.

    The payload is enriched with a ``generated_at`` timestamp if missing.
    """
    fmt = fmt.lower()
    if fmt not in _RENDERERS:
        raise OperationError(
            f"Unsupported report format '{fmt}'. Choose from {', '.join(SUPPORTED_FORMATS)}."
        )

    payload.setdefault("generated_at", datetime.now(UTC).isoformat(timespec="seconds"))
    payload.setdefault("title", "Advanced File Management Toolkit Report")

    content = _RENDERERS[fmt](payload)

    directory = ensure_directory(Path(output_dir))
    base_name = name or f"report_{_timestamp_slug()}"
    destination = unique_destination(directory / f"{base_name}.{fmt}")
    destination.write_text(content, encoding="utf-8")
    return destination


def render(payload: dict[str, Any], fmt: str = "json") -> str:
    """Render *payload* to a string without writing to disk (handy for tests)."""
    fmt = fmt.lower()
    if fmt not in _RENDERERS:
        raise OperationError(f"Unsupported report format '{fmt}'.")
    return _RENDERERS[fmt](payload)


def summarise_paths(paths: Iterable[Path]) -> dict[str, Any]:
    """Utility: build a rows payload fragment from a list of paths."""
    return {"rows": [{"path": str(p)} for p in paths]}
