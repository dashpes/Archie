"""Tests for the research CLI module."""

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from investment_monitor.research_cli import app
from investment_monitor.research.discovery import DiscoveryResult
from investment_monitor.storage import (
    StockCandidate,
)


runner = CliRunner()


class TestDiscoverCommand:
    """Tests for the discover command."""

    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.get_settings")
    @patch("investment_monitor.research_cli.DiscoveryPipeline")
    def test_discover_dry_run(
        self, mock_pipeline_cls, mock_settings, mock_session, mock_init_db
    ):
        """Test discover command in dry-run mode."""
        # Setup mocks
        mock_settings.return_value = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = DiscoveryResult(
            total_candidates=100,
            scored_candidates=50,
            top_candidates=["AAPL", "MSFT"],
            watchlist_additions=[],
            errors=[],
        )
        mock_pipeline = MagicMock()
        mock_pipeline.run_discovery = AsyncMock(return_value=mock_result)
        mock_pipeline_cls.return_value = mock_pipeline

        result = runner.invoke(app, ["discover", "--dry-run"])

        assert result.exit_code == 0
        assert "dry-run" in result.output.lower() or "dry run" in result.output.lower()

    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.get_settings")
    @patch("investment_monitor.research_cli.DiscoveryPipeline")
    def test_discover_success(
        self, mock_pipeline_cls, mock_settings, mock_session, mock_init_db
    ):
        """Test successful discover command."""
        mock_settings.return_value = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = DiscoveryResult(
            total_candidates=100,
            scored_candidates=50,
            top_candidates=["AAPL", "MSFT", "GOOGL"],
            watchlist_additions=["AAPL"],
            errors=[],
        )
        mock_pipeline = MagicMock()
        mock_pipeline.run_discovery = AsyncMock(return_value=mock_result)
        mock_pipeline_cls.return_value = mock_pipeline

        result = runner.invoke(app, ["discover"])

        assert result.exit_code == 0
        assert "100" in result.output  # total candidates
        assert "50" in result.output  # scored candidates

    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.get_settings")
    @patch("investment_monitor.research_cli.DiscoveryPipeline")
    def test_discover_with_errors(
        self, mock_pipeline_cls, mock_settings, mock_session, mock_init_db
    ):
        """Test discover command with pipeline errors."""
        mock_settings.return_value = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = DiscoveryResult(
            total_candidates=100,
            scored_candidates=0,
            top_candidates=[],
            watchlist_additions=[],
            errors=["Connection failed", "API error"],
        )
        mock_pipeline = MagicMock()
        mock_pipeline.run_discovery = AsyncMock(return_value=mock_result)
        mock_pipeline_cls.return_value = mock_pipeline

        result = runner.invoke(app, ["discover"])

        # Should still complete but report errors
        assert "error" in result.output.lower()


class TestTopCommand:
    """Tests for top command."""

    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.get_top_candidates")
    def test_top_default(self, mock_get_top, mock_session, mock_init_db):
        """Test top command with defaults."""
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        candidate1 = MagicMock(spec=StockCandidate)
        candidate1.ticker = "AAPL"
        candidate1.composite_score = 85.0
        candidate1.status = "researched"

        candidate2 = MagicMock(spec=StockCandidate)
        candidate2.ticker = "MSFT"
        candidate2.composite_score = 80.0
        candidate2.status = "watchlist"

        mock_get_top.return_value = [candidate1, candidate2]

        result = runner.invoke(app, ["top"])

        assert result.exit_code == 0
        assert "AAPL" in result.output
        assert "MSFT" in result.output
        assert "85" in result.output

    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.get_top_candidates")
    def test_top_with_limit(self, mock_get_top, mock_session, mock_init_db):
        """Test top command with limit."""
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_top.return_value = []

        result = runner.invoke(app, ["top", "--limit", "5"])

        assert result.exit_code == 0
        mock_get_top.assert_called_once()
        call_kwargs = mock_get_top.call_args[1]
        assert call_kwargs["limit"] == 5

    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.get_top_candidates")
    def test_top_with_min_score(self, mock_get_top, mock_session, mock_init_db):
        """Test top command with min-score."""
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_top.return_value = []

        result = runner.invoke(app, ["top", "--min-score", "70"])

        assert result.exit_code == 0
        mock_get_top.assert_called_once()
        call_kwargs = mock_get_top.call_args[1]
        assert call_kwargs["min_score"] == 70.0

    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.get_top_candidates")
    def test_top_empty(self, mock_get_top, mock_session, mock_init_db):
        """Test top command with no candidates."""
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_top.return_value = []

        result = runner.invoke(app, ["top"])

        assert result.exit_code == 0
        assert "no candidate" in result.output.lower()


class TestErrorHandling:
    """Tests for CLI error handling."""

    @patch("investment_monitor.research_cli.init_db")
    def test_database_error(self, mock_init_db):
        """Test handling of database initialization error."""
        mock_init_db.side_effect = Exception("Database connection failed")

        result = runner.invoke(app, ["top"])

        assert result.exit_code == 1
        assert "error" in result.output.lower()

    @patch("investment_monitor.research_cli.init_db")
    @patch("investment_monitor.research_cli.get_session")
    @patch("investment_monitor.research_cli.get_settings")
    @patch("investment_monitor.research_cli.DiscoveryPipeline")
    def test_pipeline_exception(
        self, mock_pipeline_cls, mock_settings, mock_session, mock_init_db
    ):
        """Test handling of unexpected pipeline exception."""
        mock_settings.return_value = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_pipeline = MagicMock()
        mock_pipeline.run_discovery = AsyncMock(
            side_effect=Exception("Unexpected error")
        )
        mock_pipeline_cls.return_value = mock_pipeline

        result = runner.invoke(app, ["discover"])

        assert result.exit_code == 1
        assert "error" in result.output.lower()
