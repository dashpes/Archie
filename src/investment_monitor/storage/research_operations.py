"""CRUD operations for research database models."""

from datetime import date, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from .research_models import (
    CongressionalTrade,
    SimulationResult,
    StockCandidate,
)

if TYPE_CHECKING:
    from ..simulation.models import SimulationOutput


# Candidate operations
def save_candidate(session: Session, candidate: StockCandidate) -> int:
    """Save a stock candidate, returning its ID."""
    session.add(candidate)
    session.flush()
    return candidate.id


def get_candidate_by_ticker(session: Session, ticker: str) -> StockCandidate | None:
    """Get candidate by ticker."""
    stmt = select(StockCandidate).where(StockCandidate.ticker == ticker)
    return session.scalar(stmt)


# Score operations
def get_universe_tickers(session: Session) -> list[str]:
    """Current index members, A-Z (a stable order for every scoring and refresh loop)."""
    stmt = select(StockCandidate.ticker).where(StockCandidate.in_universe.is_(True))
    return sorted(t for t in session.scalars(stmt))


def mark_universe(session: Session, members: set[str]) -> int:
    """Flag ``members`` as current and everything else as dropped. Returns rows changed."""
    members = {m.upper() for m in members}
    changed = 0
    for row in session.scalars(select(StockCandidate)):
        wanted = row.ticker.upper() in members
        if row.in_universe != wanted:
            row.in_universe = wanted
            changed += 1
    session.flush()
    return changed


# Congressional trade operations
def save_congressional_trade(session: Session, trade: CongressionalTrade) -> int:
    """Save a congressional trade, returning its ID."""
    session.add(trade)
    session.flush()
    return trade.id


def get_trades_for_ticker(
    session: Session, ticker: str, days: int = 90
) -> list[CongressionalTrade]:
    """Get recent trades for a ticker."""
    cutoff = date.today() - timedelta(days=days)
    stmt = (
        select(CongressionalTrade)
        .where(
            CongressionalTrade.ticker == ticker,
            CongressionalTrade.trade_date >= cutoff,
        )
        .order_by(CongressionalTrade.trade_date.desc())
    )
    return list(session.scalars(stmt))


# Simulation operations
def save_simulation_result(
    session: Session, output: "SimulationOutput"
) -> SimulationResult:
    """Save a SimulationOutput to the database.

    Converts the SimulationOutput Pydantic model to a SimulationResult
    ORM model and persists it.

    Args:
        session: Database session.
        output: SimulationOutput from MonteCarloAnalyzer.

    Returns:
        The saved SimulationResult with its ID.
    """

    # Convert horizon results to JSON-serializable dicts
    def horizon_to_dict(horizon_result) -> dict:
        """Convert HorizonResult to JSON-serializable dict."""
        scenarios_dict = {}
        for name, scenario in horizon_result.scenarios.items():
            scenarios_dict[name] = {
                "name": scenario.name,
                "mean": scenario.mean,
                "median": scenario.median,
                "std": scenario.std,
                "ci_80": scenario.ci_80,
                "ci_95": scenario.ci_95,
                "var_95": scenario.var_95,
                "cvar_95": scenario.cvar_95,
                "prob_loss_20pct": scenario.prob_loss_20pct,
            }

        return {
            "days": horizon_result.days,
            "base_mean": horizon_result.base_mean,
            "base_median": horizon_result.base_median,
            "base_std": horizon_result.base_std,
            "base_skewness": horizon_result.base_skewness,
            "base_percentiles": horizon_result.base_percentiles,
            "base_ci_80": horizon_result.base_ci_80,
            "base_ci_95": horizon_result.base_ci_95,
            "base_var_95": horizon_result.base_var_95,
            "base_cvar_95": horizon_result.base_cvar_95,
            "scenarios": scenarios_dict,
        }

    # Get results for each horizon (or empty dict if not present)
    results_30d = horizon_to_dict(output.results[30]) if 30 in output.results else {}
    results_90d = horizon_to_dict(output.results[90]) if 90 in output.results else {}
    results_252d = horizon_to_dict(output.results[252]) if 252 in output.results else {}

    # Convert sensitivity to dict
    sensitivity_dict = {
        "volatility_impact": output.sensitivity.volatility_impact,
        "drift_impact": output.sensitivity.drift_impact,
        "lookback_impact": output.sensitivity.lookback_impact,
        "primary_driver": output.sensitivity.primary_driver,
        "volatility_range": {
            str(k): v for k, v in output.sensitivity.volatility_range.items()
        },
        "drift_range": output.sensitivity.drift_range,
        "lookback_range": {
            str(k): v for k, v in output.sensitivity.lookback_range.items()
        },
    }

    result = SimulationResult(
        ticker=output.ticker,
        run_date=date.today(),
        entry_price=output.entry_price,
        composite_score=output.composite_score,
        num_simulations=output.num_simulations,
        lookback_days=output.lookback_days,
        volatility=output.volatility,
        drift=output.drift,
        results_30d=results_30d,
        results_90d=results_90d,
        results_252d=results_252d,
        sensitivity_analysis=sensitivity_dict,
    )

    session.add(result)
    session.flush()
    return result


def get_simulation_results(
    session: Session,
    ticker: str | None = None,
    limit: int = 10,
) -> list[SimulationResult]:
    """Get simulation results, optionally filtered by ticker.

    Args:
        session: Database session.
        ticker: Optional ticker to filter by.
        limit: Maximum number of results to return.

    Returns:
        List of SimulationResult ordered by created_at descending.
    """
    stmt = select(SimulationResult)
    if ticker is not None:
        stmt = stmt.where(SimulationResult.ticker == ticker)
    stmt = stmt.order_by(SimulationResult.created_at.desc()).limit(limit)
    return list(session.scalars(stmt))


