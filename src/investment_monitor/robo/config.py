"""Configuration for the trading bot.

Non-secret settings live in ``config/robo.yaml`` and are validated by
``RoboConfig``. The Public.com personal access token is a *secret* and is read
from the environment via the shared ``Settings`` (``PUBLIC_API_TOKEN``), never
from YAML.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


class ConfigError(ValueError):
    """A robo.yaml that fails validation, surfaced as a single clear message.

    Raised by ``RoboConfig.from_yaml`` instead of letting a raw pydantic
    ``ValidationError`` (or a YAML parse error) escape. A bad config file must
    never crash a CLI command or a service with an unhandled traceback; the
    caller logs this message and exits cleanly.
    """


class RoboCaps(BaseModel):
    """Rate and size caps enforced by the guardrail gate."""

    # Largest single BUY as a fraction of portfolio value.
    max_order_pct: float = Field(default=0.25, gt=0, le=1.0)
    # Cap on orders placed in a single run.
    max_orders_per_run: int = Field(default=5, ge=0, le=100)
    # Cap on orders placed across all runs in a day.
    max_orders_per_day: int = Field(default=10, ge=0, le=1000)
    # Fraction of an order's cost reserved for fees/slippage when checking affordability.
    fee_buffer: float = Field(default=0.01, ge=0, lt=1.0)
    # Most distinct holdings the portfolio may carry (0 = unlimited).
    max_positions: int = Field(default=0, ge=0, le=50)
    # Concentration cap: no single name above this fraction (1.0 = no cap).
    max_per_name_weight: float = Field(default=1.0, gt=0, le=1.0)


class RoboConfig(BaseModel):
    """Validated bot configuration (from ``config/robo.yaml``)."""

    # Symbols the gate will allow trading.
    allowlist: list[str] = Field(default_factory=list)
    # Symbols the gate must never BUY (sells/exits always allowed). Operator-curated;
    # the system also auto-learns broker-refused, un-buyable names into a separate
    # persisted learned blocklist (see robo/blocklist.py). Union of both is enforced.
    blocklist: list[str] = Field(default_factory=list)
    caps: RoboCaps = Field(default_factory=RoboCaps)
    # Safety: simulate everything and place no real orders when True. Default True.
    dry_run: bool = True
    # Only PLACE live orders during US market hours.
    require_market_hours: bool = True
    # Optional specific Public account id to use (required if more than one exists).
    account_id: str = ""

    @field_validator("allowlist", "blocklist")
    @classmethod
    def _upper_symbol_lists(cls, v: list[str]) -> list[str]:
        return [s.upper() for s in v]

    @classmethod
    def from_yaml(cls, path: Path) -> "RoboConfig":
        """Load and validate config from a YAML file (defaults if missing).

        Any validation or parse failure is re-raised as a single, actionable
        :class:`ConfigError` (which key, the bound, the offending value).
        """
        if not path.exists():
            return cls()
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"could not parse {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(
                f"{path} must contain a YAML mapping at the top level, "
                f"got {type(data).__name__}"
            )
        try:
            return cls(**data)
        except ValidationError as exc:
            raise ConfigError(_format_validation_error(path, exc)) from exc


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    """Render a pydantic ValidationError as one clear, actionable message."""
    lines = [f"invalid robo config in {path}:"]
    for err in exc.errors():
        key = ".".join(str(p) for p in err["loc"]) or "(root)"
        msg = err["msg"]
        if "input" in err:
            lines.append(f"  - {key}: {msg} (got {err['input']!r})")
        else:
            lines.append(f"  - {key}: {msg}")
    return "\n".join(lines)
