"""Database storage module."""

from .database import get_session, init_db
from .models import (
    Base,
    InsiderTransaction,
    NewsItem,
    Price,
)
from .operations import (
    get_insider_transactions,
    get_latest_price,
    get_prices,
    get_recent_news,
    get_unclassified_news,
    insider_transaction_exists,
    news_exists,
    price_exists,
    save_insider_transaction,
    save_news_item,
    save_price,
    save_prices,
)
from .research_models import (
    CANDIDATE_STATUSES,
    CandidateScore,
    CongressionalTrade,
    SimulationResult,
    StockCandidate,
)
from .research_operations import (
    get_candidate_by_ticker,
    get_candidates_by_status,
    get_high_scoring_candidates,
    get_latest_score,
    get_score_history,
    get_simulation_results,
    get_top_candidates,
    get_trades_for_ticker,
    save_candidate,
    save_congressional_trade,
    save_score,
    save_simulation_result,
)
from .robo_models import RoboOrder, RoboRun
from .robo_operations import (
    count_placed_orders_today,
    finalize_robo_run,
    get_filled_robo_orders,
    get_recent_robo_runs,
    get_robo_orders_for_run,
    get_unfilled_placed_orders,
    save_robo_order,
    save_robo_run,
)
from .event_models import SIGNAL_ITEM_CODES, MaterialEvent
from .event_operations import get_material_events, material_event_exists
from .insight_models import (
    FINDING_CONGRESS_CLUSTER,
    FINDING_INSIDER_CLUSTER,
    FINDING_MULTI_SOURCE,
    ConfluenceFinding,
)
from .insight_operations import (
    finding_exists_for_date,
    get_recent_findings,
    save_finding,
)
from .job_models import JobRun, last_job_success, record_job_run
from .retention import RetentionConfig, prune_old_data

__all__ = [
    # Database
    "init_db",
    "get_session",
    "Base",
    # Core models
    "Price",
    "InsiderTransaction",
    "NewsItem",
    "ETFHolding",
    # Core operations
    "save_price",
    "save_prices",
    "get_latest_price",
    "get_prices",
    "price_exists",
    "save_insider_transaction",
    "get_insider_transactions",
    "insider_transaction_exists",
    "save_news_item",
    "news_exists",
    "get_unclassified_news",
    "get_recent_news",
    # Research models
    "CANDIDATE_STATUSES",
    "StockCandidate",
    "CandidateScore",
    "CongressionalTrade",
    "SimulationResult",
    # Research operations - Candidate
    "save_candidate",
    "get_candidate_by_ticker",
    "get_candidates_by_status",
    "get_top_candidates",
    # Research operations - Score
    "save_score",
    "get_latest_score",
    "get_score_history",
    # Research operations - Congressional Trade
    "save_congressional_trade",
    "get_trades_for_ticker",
    # Research operations - Simulation
    "save_simulation_result",
    "get_simulation_results",
    "get_high_scoring_candidates",
    # Robo advisor models
    "RoboRun",
    "RoboOrder",
    # Robo advisor operations
    "save_robo_run",
    "finalize_robo_run",
    "save_robo_order",
    "get_recent_robo_runs",
    "get_robo_orders_for_run",
    "get_filled_robo_orders",
    "get_unfilled_placed_orders",
    "count_placed_orders_today",
    # Material corporate events (SEC 8-K)
    "MaterialEvent",
    "SIGNAL_ITEM_CODES",
    "material_event_exists",
    "get_material_events",
    # Confluence / insight engine
    "ConfluenceFinding",
    "FINDING_INSIDER_CLUSTER",
    "FINDING_CONGRESS_CLUSTER",
    "FINDING_MULTI_SOURCE",
    "save_finding",
    "finding_exists_for_date",
    "get_recent_findings",
    # Retention / cleanup
    "RetentionConfig",
    "prune_old_data",
    # Scheduler job runs
    "JobRun",
    "record_job_run",
    "last_job_success",
    "MemoryEmbedding",
    "save_embedding",
    "search_similar",
    "is_duplicate",
    "cosine_similarity",
]
