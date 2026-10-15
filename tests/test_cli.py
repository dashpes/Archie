"""Tests for the data-collection CLI."""

from unittest.mock import patch

from investment_monitor.cli import create_parser, main


class TestCreateParser:
    def test_default_type_is_collect_broad(self):
        args = create_parser().parse_args([])
        assert args.type == "collect-broad"
        assert args.days_back == 1
        assert args.log_level == "INFO"

    def test_all_run_types_accepted(self):
        parser = create_parser()
        for run_type in ["collect-broad", "insights", "prune"]:
            assert parser.parse_args(["-t", run_type]).type == run_type

    def test_prune_windows(self):
        args = create_parser().parse_args(
            ["-t", "prune", "--insider-days", "30", "--news-days", "7", "--findings-days", "90"]
        )
        assert (args.insider_days, args.news_days, args.price_days, args.findings_days) == (
            30, 7, 0, 90,
        )

    def test_quiet_flag(self):
        assert create_parser().parse_args(["-q"]).quiet is True


class TestMain:
    def test_insights_prints_findings(self, capsys):
        findings = [{"score": 4.5, "narrative": "3 insiders bought AAPL"}]
        with patch("investment_monitor.analysis.confluence.run_confluence", return_value=findings):
            assert main(["-t", "insights"]) == 0
        out = capsys.readouterr().out
        assert "1 confluence finding" in out
        assert "AAPL" in out

    def test_insights_reports_error(self, capsys):
        with patch(
            "investment_monitor.analysis.confluence.run_confluence",
            side_effect=RuntimeError("db locked"),
        ):
            assert main(["-t", "insights"]) == 1
        assert "db locked" in capsys.readouterr().err

    def test_collect_broad_returns_failure_when_a_collector_fails(self, capsys, tmp_path):
        class _Result:
            success = False

            def __str__(self):
                return "insider: failed"

        with patch(
            "investment_monitor.broad_collect.run_broad_collection_sync",
            return_value=[_Result()],
        ), patch("investment_monitor.logging_config.setup_logging"), patch(
            "investment_monitor.analysis.news_processor.classify_unscored_sentiment"
        ):
            assert main(["-t", "collect-broad", "--days-back", "2"]) == 1
        assert "insider: failed" in capsys.readouterr().out
