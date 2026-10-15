"""Future component contracts.

These protocols document extension points. The read-only paper account adapter
is in ``nomadquant.broker``. Daily bars are in ``nomadquant.marketdata``.

Order placement is intentionally absent. A later order gateway, if one is
added, may be called only after ``RiskEngine.evaluate`` returns an approval.
Research agents must never receive that gateway or a broker order client.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class Bar(BaseModel):
    """One daily bar and the time at which this system models it as knowable.

    ``as_of`` is NomadQuant's modeled availability time. It is not Alpaca's
    symbol-mapping ``asof`` parameter, and it is not proof of what a vendor
    published on that historical date.
    """

    symbol: str
    session_date: date
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    as_of: datetime
    provider: str
    feed: Literal["sip", "iex"]
    adjustment: Literal["raw"]
    timeframe: Literal["1Day"]
    currency: str
    first_retrieved_at: datetime


class MarketDataProvider(Protocol):
    """Historical data with an explicit knowledge cutoff.

    Implementations must not return a bar whose modeled availability is later
    than the requested cutoff. A bar timestamp inside the window is not enough.
    Missing sessions stay missing.
    """

    def get_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        as_of: datetime,
    ) -> list[Bar]:
        """Return bars in ``[start, end]`` that were model-available at ``as_of``."""


class Hypothesis(BaseModel):
    statement: str
    citations: list[str] = Field(default_factory=list)


class ResearchNote(BaseModel):
    hypothesis: Hypothesis
    findings: str
    caveats: str


class ResearchAgent(Protocol):
    """A tool-using research assistant.

    Implementations may read data and write notes. They must not submit,
    cancel, or replace broker orders.
    """

    def review(self, hypothesis: Hypothesis) -> ResearchNote:
        """Critique a falsifiable hypothesis and record caveats."""


class StrategyContext(BaseModel):
    as_of: datetime
    virtual_capital_usd: Decimal


class TargetPosition(BaseModel):
    symbol: str
    target_weight: Decimal


class Strategy(Protocol):
    """Map a point-in-time context to target weights.

    An empty sequence is a valid decision not to trade.
    """

    def targets(self, context: StrategyContext) -> list[TargetPosition]:
        """Return long-only target weights, or none."""


class BacktestConfig(BaseModel):
    start: datetime
    end: datetime
    initial_capital_usd: Decimal


class BacktestResult(BaseModel):
    """Simulated performance. This is never realized profit."""

    label: Literal["backtest"] = "backtest"
    net_return: Decimal | None = None
    max_drawdown: Decimal | None = None
    notes: str = ""


class BacktestEngine(Protocol):
    """Reproducible historical evaluation. Not a broker."""

    def run(self, strategy: Strategy, config: BacktestConfig) -> BacktestResult:
        """Evaluate ``strategy`` on data available inside the config window."""


class OrderIntent(BaseModel):
    """A proposed buy. Phase 1 does not accept or persist these."""

    symbol: str
    side: Literal["buy"]
    notional_usd: Decimal
    idempotency_key: str


class RiskDecision(BaseModel):
    approved: bool
    reasons: list[str]


class RiskEngine(Protocol):
    """Independent check that sits in front of any future order gateway.

    Agents do not implement this protocol and cannot override a rejection.
    """

    def evaluate(self, intent: OrderIntent) -> RiskDecision:
        """Approve or reject one intent. Missing data must fail closed."""


class AccountView(BaseModel):
    equity: Decimal
    buying_power: Decimal
    cash: Decimal
    currency: str


class PositionView(BaseModel):
    symbol: str
    qty: Decimal
    side: str
    market_value: Decimal


class PaperBroker(Protocol):
    """Read-only view of a paper account.

    There is no submit, cancel, or liquidate method. Adding one to this
    protocol would let a caller bypass ``RiskEngine``.
    """

    def get_account(self) -> AccountView:
        """Return cash, equity, and buying power."""

    def get_positions(self) -> list[PositionView]:
        """Return open paper positions."""
