"""Scheduler job runs: one row per attempt, so a service can ask when a job last succeeded."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .models import Base

if TYPE_CHECKING:
    from investment_monitor.scheduler import JobOutcome


class JobRun(Base):
    """One scheduler attempt at a job. Timestamps are naive UTC."""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    return_code: Mapped[int] = mapped_column(Integer, nullable=False)
    stderr_tail: Mapped[str | None] = mapped_column(Text, nullable=True)


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def record_job_run(session: Session, outcome: JobOutcome) -> JobRun:
    row = JobRun(
        name=outcome.name,
        started_at=_naive_utc(outcome.started),
        finished_at=_naive_utc(outcome.finished),
        return_code=outcome.return_code,
        stderr_tail=outcome.stderr_tail or None,
    )
    session.add(row)
    session.flush()
    return row


def last_job_success(session: Session, name: str) -> datetime | None:
    """Naive-UTC start time of the newest successful run of ``name``, or None."""
    stmt = (
        select(JobRun.started_at)
        .where(JobRun.name == name, JobRun.return_code == 0)
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)
