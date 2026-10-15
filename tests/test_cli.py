"""Tests for the ``investment-data`` CLI."""

from datetime import datetime
from unittest.mock import patch

from typer.testing import CliRunner

from investment_monitor.cli import app, data_jobs
from investment_monitor.collectors.base import CollectorResult

runner = CliRunner()


def _result(name: str, ok: bool) -> CollectorResult:
    now = datetime(2026, 10, 12, 8, 0)
    return CollectorResult(
        collector_name=name, success=ok, records_collected=0,
        errors=[] if ok else ["down"], started_at=now, finished_at=now,
    )


def test_version():
    out = runner.invoke(app, ["--version"])
    assert out.exit_code == 0 and "investment-data" in out.output


def test_collect_default_runs_all_sources(tmp_path):
    with patch("investment_monitor.cli.setup_logging"), patch(
        "investment_monitor.broad_collect.run_broad_collection_sync",
        return_value=[_result("insider", True)],
    ) as run:
        out = runner.invoke(app, ["collect", "--days-back", "2"])
    assert out.exit_code == 0, out.output
    assert run.call_args.kwargs["sources"] == ("insider", "events", "prices", "news", "congress")
    assert run.call_args.kwargs["days_back"] == 2


def test_collect_selects_sources_and_fails_on_a_failed_source():
    with patch("investment_monitor.cli.setup_logging"), patch(
        "investment_monitor.broad_collect.run_broad_collection_sync",
        return_value=[_result("news", False)],
    ) as run:
        out = runner.invoke(app, ["collect", "-s", "news", "-s", "prices"])
    assert out.exit_code == 1
    assert run.call_args.kwargs["sources"] == ("news", "prices")


def test_collect_rejects_unknown_source():
    with patch("investment_monitor.cli.setup_logging"):
        out = runner.invoke(app, ["collect", "-s", "tiktok"])
    assert out.exit_code == 2 and "unknown source" in out.output


def test_insights_prints_findings():
    findings = [{"score": 4.5, "narrative": "3 insiders bought AAPL"}]
    with patch("investment_monitor.cli.setup_logging"), patch(
        "investment_monitor.analysis.confluence.run_confluence", return_value=findings
    ):
        out = runner.invoke(app, ["insights"])
    assert out.exit_code == 0 and "AAPL" in out.output


def test_health_reports_missing_heartbeat(tmp_path):
    with patch("investment_monitor.cli.setup_logging"), patch(
        "investment_monitor.scheduler.heartbeat_age_s", return_value=None
    ):
        out = runner.invoke(app, ["health", "data", "300"])
    assert out.exit_code == 1 and "missing" in out.output


def test_health_ok_when_fresh():
    with patch("investment_monitor.cli.setup_logging"), patch(
        "investment_monitor.scheduler.heartbeat_age_s", return_value=12.0
    ):
        out = runner.invoke(app, ["health", "data", "300"])
    assert out.exit_code == 0


def test_data_jobs_cover_every_source_and_are_unique():
    jobs = data_jobs()
    names = [j.name for j in jobs]
    assert len(names) == len(set(names))
    argv = " ".join(" ".join(j.argv) for j in jobs)
    for source in ("insider", "events", "prices", "news", "congress"):
        assert source in argv
    assert {"label", "insights", "universe", "prune"} <= set(names)


def test_research_commands_are_mounted():
    out = runner.invoke(app, ["research", "--help"])
    assert out.exit_code == 0 and "discover" in out.output
