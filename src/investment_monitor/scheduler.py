"""In-process job scheduler for the data and bot services.

One long-running process per container. Each job is a CLI subcommand run as a
subprocess with a timeout, one at a time, so a hung fetch is killed and a crash
cannot take the loop down. Every run lands in the ``job_runs`` table; a job is
due when no success exists since its most recent slot (catch-up), unless the
slot is older than its ``max_lateness``.

Times are US Eastern (``America/New_York``) because every schedule here is
pinned to the market day.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

from investment_monitor.config import Settings, get_settings
from investment_monitor.storage import get_session, init_db, last_job_success, record_job_run

ET = ZoneInfo("America/New_York")
WEEKDAYS = frozenset({0, 1, 2, 3, 4})
MON_TO_SAT = frozenset({0, 1, 2, 3, 4, 5})

# (now, last_ok) -> due?  Both datetimes are tz-aware in ET; last_ok is None on a fresh DB.
Due = Callable[[datetime, datetime | None], bool]

# Email after this many consecutive failures of one job, and again every N after.
FAILURE_STREAK = 3


@dataclass(frozen=True)
class Job:
    name: str
    argv: list[str]
    due: Due
    timeout_s: int = 1800


@dataclass(frozen=True)
class JobOutcome:
    name: str
    started: datetime
    finished: datetime
    return_code: int
    stderr_tail: str

    @property
    def ok(self) -> bool:
        return self.return_code == 0


def every(minutes: int) -> Due:
    """Due when the last success is older than ``minutes`` (or there is none)."""
    gap = timedelta(minutes=minutes)

    def _due(now: datetime, last_ok: datetime | None) -> bool:
        return last_ok is None or now - last_ok >= gap

    return _due


def daily_at(
    hour: int,
    minute: int = 0,
    *,
    weekdays: frozenset[int] | None = None,
    max_lateness_s: int | None = None,
) -> Due:
    """Due once per slot: when no success exists since the most recent ``hour:minute``.

    ``weekdays`` restricts slots (0 = Monday). A missed slot is caught up at any
    later time unless ``max_lateness_s`` says the slot is too old to run.
    """

    def _latest_slot(now: datetime) -> datetime:
        slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot > now:
            slot -= timedelta(days=1)
        while weekdays is not None and slot.weekday() not in weekdays:
            slot -= timedelta(days=1)
        return slot

    def _due(now: datetime, last_ok: datetime | None) -> bool:
        slot = _latest_slot(now)
        if last_ok is not None and last_ok >= slot:
            return False
        if max_lateness_s is not None and now - slot > timedelta(seconds=max_lateness_s):
            return False
        return True

    return _due


def weekly_at(weekday: int, hour: int, minute: int = 0) -> Due:
    return daily_at(hour, minute, weekdays=frozenset({weekday}))


def run_job(job: Job, *, now: datetime, run_fn=subprocess.run) -> JobOutcome:
    """Run one job to completion (or timeout). Never raises."""
    started = now
    try:
        proc = run_fn(job.argv, capture_output=True, text=True, timeout=job.timeout_s)
        code, tail = proc.returncode, (proc.stderr or "")[-2000:]
    except subprocess.TimeoutExpired:
        code, tail = -1, f"killed after {job.timeout_s}s timeout"
    except OSError as exc:
        code, tail = -2, f"could not start: {exc}"
    finished = datetime.now(ET) if now.tzinfo else datetime.now()
    if code == 0:
        logger.info("job {n} ok", n=job.name)
    else:
        logger.error("job {n} failed rc={c}: {t}", n=job.name, c=code, t=tail[-300:])
    return JobOutcome(job.name, started, finished, code, tail)


def heartbeat_path(settings: Settings, role: str) -> Path:
    return Path(settings.data_dir) / f"heartbeat-{role}"


def heartbeat_age_s(settings: Settings, role: str) -> float | None:
    path = heartbeat_path(settings, role)
    if not path.exists():
        return None
    return time.time() - path.stat().st_mtime


def serve(
    jobs: list[Job],
    *,
    role: str,
    settings: Settings | None = None,
    tick_s: int = 60,
    now_fn: Callable[[], datetime] | None = None,
    run_fn=subprocess.run,
    notify_fn: Callable[[Settings, str], None] | None = None,
    max_ticks: int | None = None,
) -> None:
    """Loop forever (or ``max_ticks`` for tests): run due jobs, record, heartbeat."""
    settings = settings or get_settings()
    now_fn = now_fn or (lambda: datetime.now(ET))
    notify = notify_fn or _email_failure
    init_db(settings.db_path)
    streak: dict[str, int] = {}
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        ticks += 1
        for job in jobs:
            now = now_fn()
            with get_session() as session:
                last_ok = last_job_success(session, job.name)
            if last_ok is not None:
                last_ok = last_ok.replace(tzinfo=timezone.utc).astimezone(ET)
            if not job.due(now, last_ok):
                continue
            outcome = run_job(job, now=now, run_fn=run_fn)
            with get_session() as session:
                record_job_run(session, outcome)
            if outcome.ok:
                streak[job.name] = 0
            else:
                streak[job.name] = streak.get(job.name, 0) + 1
                if streak[job.name] % FAILURE_STREAK == 0:
                    notify(
                        settings,
                        f"{role}: job '{job.name}' failed {streak[job.name]} times in a row "
                        f"(rc={outcome.return_code}).\n\n{outcome.stderr_tail}",
                    )
        path = heartbeat_path(settings, role)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        if max_ticks is None or ticks < max_ticks:
            time.sleep(tick_s)


def _email_failure(settings: Settings, message: str) -> None:
    from investment_monitor.robo.notify import notify_error

    notify_error(settings, message=message)
