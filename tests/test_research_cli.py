"""Tests for the research CLI (discover, top)."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from investment_monitor.research_cli import app

runner = CliRunner()


def _session_cm():
    cm = MagicMock()
    cm.__enter__.return_value = MagicMock()
    cm.__exit__.return_value = False
    return cm


class TestDiscoverCommand:
    @patch("investment_monitor.research_cli.score_universe")
    @patch("investment_monitor.research_cli.refresh_fundamentals", new_callable=AsyncMock)
    @patch("investment_monitor.research_cli.UniverseCollector")
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_settings")
    def test_discover_runs_universe_refresh_and_score(self, settings, init_db, get_session, universe, refresh, score):
        settings.return_value = SimpleNamespace(db_path="x.db", config_dir=Path("no-such-dir"))
        get_session.return_value = _session_cm()
        universe.return_value.collect = AsyncMock(return_value=SimpleNamespace(records_collected=3))
        refresh.return_value = SimpleNamespace(fetched=2, requested=2, errors=[])
        score.return_value = SimpleNamespace(scored=10, filtered=1, no_snapshot=2, universe=13, top=[("AAA", 81.2)])
        out = runner.invoke(app, ["discover"])
        assert out.exit_code == 0, out.output
        assert "universe: 3 new" in out.output
        assert "refreshed 2/2" in out.output
        assert "10 scored" in out.output and "AAA 81" in out.output

    @patch("investment_monitor.research_cli.init_db", side_effect=RuntimeError("locked"))
    @patch("investment_monitor.research_cli.get_settings")
    def test_discover_reports_errors(self, settings, init_db):
        settings.return_value = SimpleNamespace(db_path="x.db", config_dir="cfg")
        out = runner.invoke(app, ["discover"])
        assert out.exit_code == 1 and "locked" in out.output


class TestTopCommand:
    @patch("investment_monitor.research_cli.top_scores")
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_settings")
    def test_top_lists_scores(self, settings, init_db, get_session, top):
        settings.return_value = SimpleNamespace(db_path="x.db")
        get_session.return_value = _session_cm()
        top.return_value = [
            SimpleNamespace(ticker="AAA", composite=81.25, value=70.0, growth=None, quality=90.0,
                            momentum=80.0, sentiment=None, as_of=date(2026, 10, 10)),
        ]
        out = runner.invoke(app, ["top", "--limit", "5", "--min-score", "60"])
        assert out.exit_code == 0, out.output
        assert "AAA" in out.output and "81.2" in out.output and "2026-10-10" in out.output
        assert top.call_args.kwargs == {"limit": 5, "min_composite": 60.0}

    @patch("investment_monitor.research_cli.top_scores", return_value=[])
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_settings")
    def test_top_empty(self, settings, init_db, get_session, top):
        settings.return_value = SimpleNamespace(db_path="x.db")
        get_session.return_value = _session_cm()
        out = runner.invoke(app, ["top"])
        assert out.exit_code == 0 and "No scored tickers" in out.output
