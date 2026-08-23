"""Shared building blocks for core operations.

Every feature returns an :class:`OperationResult`, which gives the CLI and the
reporting layer a uniform structure to work with: how many items were touched,
how many bytes, what individual actions happened, and any errors that were
handled gracefully.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Action:
    """A single, concrete thing the toolkit did (or would do in dry-run)."""

    kind: str  # e.g. "move", "delete", "copy", "rename"
    source: str
    destination: str | None = None
    size: int = 0
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"action": self.kind, "source": self.source}
        if self.destination is not None:
            data["destination"] = self.destination
        if self.size:
            data["size"] = self.size
        if self.note:
            data["note"] = self.note
        return data


@dataclass
class OperationResult:
    """Uniform result object shared by all core operations."""

    operation: str
    dry_run: bool = False
    actions: list[Action] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    items: int = 0
    bytes: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
    _start: float = field(default_factory=time.perf_counter, repr=False)
    duration_ms: int = 0

    def add(self, action: Action) -> None:
        self.actions.append(action)
        self.items += 1
        self.bytes += max(action.size, 0)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def finish(self) -> OperationResult:
        self.duration_ms = int((time.perf_counter() - self._start) * 1000)
        return self

    # -- serialisation -----------------------------------------------------
    def summary(self) -> dict[str, Any]:
        data = {
            "operation": self.operation,
            "dry_run": self.dry_run,
            "items": self.items,
            "bytes": self.bytes,
            "errors": len(self.errors),
            "duration_ms": self.duration_ms,
        }
        data.update(self.extra)
        return data

    def to_payload(self, *, title: str | None = None) -> dict[str, Any]:
        return {
            "title": title or f"{self.operation.title()} Report",
            "summary": self.summary(),
            "rows": [action.as_dict() for action in self.actions],
            "errors": self.errors,
        }
