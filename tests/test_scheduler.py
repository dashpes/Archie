"""Tests for the in-process scheduler."""

import subprocess
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from investment_monitor import scheduler
from investment_monitor.scheduler import (
    ET,
    MON_TO_SAT,
    Job,
    daily_at,
    every,
    run_job,
    serve,
    weekly_at,
)
from investment_monitor.storage import JobRun, get_session, init_db

MON_0800 = datetime(2026, 10, 12, 8, 0, tzinfo=ET)  # a Monday


def _settings(tmp_path):
    return SimpleNamespace(
        db_path=str(tmp_path / "s.db"), data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
    )


# --- due rules -------------------------------------------------------------------

def test_every_is_due_on_fresh_db_and_after_gap():
    due = every(60)
    assert due(MON_0800, None)
    assert not due(MON_0800, MON_0800 - timedelta(minutes=30))
    assert due(MON_0800, MON_0800 - timedelta(minutes=60))


def test_daily_at_is_due_once_per_slot():
    due = daily_at(6, 30)
    slot = MON_0800.replace(hour=6, minute=30)
    assert due(MON_0800, None)                              # never ran
    assert due(MON_0800, slot - timedelta(days=1))          # last ran yesterday
    assert not due(MON_0800, slot + timedelta(minutes=5))   # already ran this slot
    assert not due(MON_0800.replace(hour=6, minute=0), slot - timedelta(days=1) + timedelta(hours=1))


def test_daily_at_catches_up_a_missed_slot_later_in_the_day():
    due = daily_at(6, 30)
    assert due(MON_0800.replace(hour=20), MON_0800.replace(hour=6, minute=30) - timedelta(days=1))


def test_daily_at_respects_max_lateness():
    due = daily_at(15, 45, max_lateness_s=15 * 60)
    fri_1550 = datetime(2026, 10, 9, 15, 50, tzinfo=ET)
    fri_1700 = datetime(2026, 10, 9, 17, 0, tzinfo=ET)
    assert due(fri_1550, None)
    assert not due(fri_1700, None)  # slot too old: never trade a missed slot late


def test_daily_at_weekdays_skips_sunday_slot():
    due = daily_at(6, 30, weekdays=MON_TO_SAT)
    sun_0900 = datetime(2026, 10, 11, 9, 0, tzinfo=ET)
    sat_0630 = datetime(2026, 10, 10, 6, 30, tzinfo=ET)
    assert not due(sun_0900, sat_0630)          # Saturday slot already satisfied
    assert due(sun_0900, sat_0630 - timedelta(days=1))


def test_weekly_at_uses_one_weekday():
    due = weekly_at(6, 5, 0)  # Sunday 05:00
    sun_0600 = datetime(2026, 10, 11, 6, 0, tzinfo=ET)
    assert due(sun_0600, None)
    assert not due(sun_0600, sun_0600 - timedelta(minutes=30))
    assert not due(MON_0800, sun_0600 - timedelta(minutes=30))


# --- running one job ---------------------------------------------------------------

def test_run_job_records_return_code_and_stderr_tail():
    job = Job("echo", [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"], every(1))
    out = run_job(job, now=MON_0800)
    assert out.return_code == 3 and "boom" in out.stderr_tail and not out.ok


def test_run_job_kills_on_timeout():
    job = Job("hang", [sys.executable, "-c", "import time; time.sleep(5)"], every(1), timeout_s=1)
    out = run_job(job, now=MON_0800)
    assert out.return_code == -1 and "timeout" in out.stderr_tail


def test_run_job_survives_missing_binary():
    out = run_job(Job("nope", ["/nonexistent/binary"], every(1)), now=MON_0800)
    assert out.return_code == -2


# --- the loop ----------------------------------------------------------------------

def _fake_run(returncode: int):
    def _run(argv, **_):
        return subprocess.CompletedProcess(argv, returncode, stdout="", stderr="err")
    return _run


def test_serve_runs_due_jobs_records_them_and_heartbeats(tmp_path):
    settings = _settings(tmp_path)
    jobs = [Job("a", ["a"], every(60)), Job("b", ["b"], daily_at(23, 59))]
    serve(jobs, role="data", settings=settings, now_fn=lambda: MON_0800,
          run_fn=_fake_run(0), notify_fn=MagicMock(), max_ticks=2, tick_s=0)
    with get_session() as s:
        names = [r.name for r in s.query(JobRun).order_by(JobRun.id)]
    # tick 1 runs both (fresh DB); tick 2 at the same instant runs neither again.
    assert names == ["a", "b"]
    assert scheduler.heartbeat_age_s(settings, "data") is not None


def test_serve_emails_after_three_consecutive_failures(tmp_path):
    settings = _settings(tmp_path)
    notify = MagicMock()
    clock = iter(MON_0800 + timedelta(hours=h) for h in range(10))
    serve([Job("a", ["a"], every(1))], role="data", settings=settings,
          now_fn=lambda: next(clock), run_fn=_fake_run(1), notify_fn=notify, max_ticks=3, tick_s=0)
    notify.assert_called_once()
    assert "3 times in a row" in notify.call_args.args[1]


def test_serve_success_resets_the_streak(tmp_path):
    settings = _settings(tmp_path)
    notify = MagicMock()
    codes = iter([1, 1, 0, 1, 1])
    clock = iter(MON_0800 + timedelta(hours=h) for h in range(10))

    def _run(argv, **_):
        return subprocess.CompletedProcess(argv, next(codes), stdout="", stderr="")

    serve([Job("a", ["a"], every(1))], role="data", settings=settings,
          now_fn=lambda: next(clock), run_fn=_run, notify_fn=notify, max_ticks=5, tick_s=0)
    notify.assert_not_called()
    init_db(settings.db_path)
    with get_session() as s:
        assert [r.return_code for r in s.query(JobRun).order_by(JobRun.id)] == [1, 1, 0, 1, 1]
