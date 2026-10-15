"""Immutable experiment configuration and result shapes."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class CostModel(BaseModel):
    commission_usd: Decimal = Decimal("0")
    spread_bps: Decimal = Decimal("1")
    slippage_bps: Decimal = Decimal("1")
    min_notional_usd: Decimal = Decimal("1")
    quantity_precision: int = 6


class WindowSpec(BaseModel):
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date


class ExperimentConfig(BaseModel):
    """Versioned research configuration. No credentials."""

    experiment_id: str
    hypothesis_id: str
    title: str
    description: str
    citations: list[str] = Field(default_factory=list)
    symbols: list[str]
    feed: Literal["sip", "iex"]
    adjustment: Literal["raw"] = "raw"
    research_mode: Literal["price_only"] = "price_only"
    data_start: date
    data_end: date
    evaluation_start: date
    evaluation_end: date
    windows: WindowSpec
    strategy_id: str
    lookback_sessions: int
    skip_sessions: int = 0
    rebalance: Literal["monthly_first_session"] = "monthly_first_session"
    initial_capital_usd: Decimal = Decimal("100")
    costs: CostModel = Field(default_factory=CostModel)
    benchmarks: list[str] = Field(default_factory=lambda: ["spy_buy_hold", "cash", "tsmom_6m"])
    caveats: list[str] = Field(default_factory=list)
    engine_version: str = "1.0.0"


class EquityPoint(BaseModel):
    session_date: date
    equity: Decimal
    cash: Decimal
    exposure: Decimal
    drawdown: Decimal
    window: str


class SimulatedTrade(BaseModel):
    session_date: date
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    notional: Decimal
    commission: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    reason: str
    is_simulated: Literal[True] = True
    is_broker_order: Literal[False] = False


class SimulatedDecision(BaseModel):
    session_date: date
    decision_timestamp: str
    data_cutoff: str
    symbol: str
    signal: str
    feature_inputs: dict[str, str]
    proposed_target_weight: Decimal
    action: Literal["buy", "sell", "hold", "reject", "no_trade"]
    rationale: str
    evidence_hash: str
    fill_session: date | None = None
    fill_price: Decimal | None = None
    portfolio_before: dict[str, str]
    portfolio_after: dict[str, str]
    warnings: list[str] = Field(default_factory=list)
    is_simulated: Literal[True] = True
    is_broker_order: Literal[False] = False


class MetricSet(BaseModel):
    window: str
    start_capital: Decimal
    end_capital: Decimal
    gross_return: Decimal | None
    net_return: Decimal | None
    max_drawdown: Decimal | None
    annualized_volatility: Decimal | None
    sharpe: Decimal | None
    sortino: Decimal | None
    exposure: Decimal | None
    turnover: Decimal | None
    trade_count: int
    total_costs: Decimal
    sample_sessions: int
    unavailable: list[str] = Field(default_factory=list)


class StrategyResult(BaseModel):
    strategy_id: str
    label: Literal["backtest"] = "backtest"
    metrics: list[MetricSet]
    equity: list[EquityPoint]
    trades: list[SimulatedTrade]
    decisions: list[SimulatedDecision]
