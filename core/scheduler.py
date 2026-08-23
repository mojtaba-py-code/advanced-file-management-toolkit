"""Lightweight job scheduler for recurring maintenance tasks.

Wraps the ``schedule`` library to run any callable at a fixed interval (every
N minutes/hours/days) or at a specific time each day. Designed so the CLI can
schedule backups, cleanups, organization, sync or reports.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from utils.exceptions import OperationError
from utils.logging_config import get_logger

logger = get_logger("scheduler")

try:
    import schedule

    _SCHEDULE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCHEDULE_AVAILABLE = False

_UNITS = ("minutes", "hours", "days")


@dataclass
class ScheduledJob:
    """A named recurring job."""

    name: str
    func: Callable[[], object]
    interval: int = 1
    unit: str = "hours"
    at: str | None = None  # "HH:MM" for daily jobs


def _run_job(job: ScheduledJob) -> None:
    logger.info("Running scheduled job: %s", job.name)
    try:
        job.func()
        logger.info("Scheduled job '%s' finished.", job.name)
    except Exception as exc:
        logger.error("Scheduled job '%s' failed: %s", job.name, exc)


def run_scheduler(jobs: list[ScheduledJob], *, run_once: bool = False) -> None:
    """Register *jobs* and run the scheduling loop.

    ``run_once=True`` executes each job a single time immediately and returns —
    useful for tests and for a "run now" mode.
    """
    if not _SCHEDULE_AVAILABLE:
        raise OperationError(
            "The 'schedule' package is required for scheduling. Install it with: pip install schedule"
        )
    if not jobs:
        raise OperationError("No jobs to schedule.")

    if run_once:
        for job in jobs:
            _run_job(job)
        return

    for job in jobs:
        if job.unit not in _UNITS:
            raise OperationError(f"Invalid interval unit '{job.unit}'. Use {', '.join(_UNITS)}.")
        every = schedule.every(job.interval)
        unit_scheduler = getattr(every, job.unit)
        if job.at and job.unit == "days":
            unit_scheduler.at(job.at).do(_run_job, job)
        else:
            unit_scheduler.do(_run_job, job)
        logger.info(
            "Scheduled '%s' every %d %s%s",
            job.name,
            job.interval,
            job.unit,
            f" at {job.at}" if job.at else "",
        )

    logger.info("Scheduler started. Press Ctrl-C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        logger.info("Scheduler stopped by user.")
