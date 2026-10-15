"""Regression tests for research accounting, time, replay, and tool bounds."""

from datetime import UTC, date, datetime
from decimal import Decimal
from math import sqrt
from pathlib import Path

import pytest

from nomadquant.marketdata.calendar import is_early_close
from nomadquant.research.engine import bar_open_timestamp
from nomadquant.research.metrics import compute_metrics
from nomadquant.research.models import CostModel, EquityPoint
from nomadquant.research.portfolio import Portfolio
from nomadquant.research.store import ExperimentImmutableError, ResearchStore
from nomadquant.research.tools import ResearchToolRegistry, ToolError
from nomadquant.research.verify import verify_run


def test_spread_and_slippage_are_charged_once_on_a_buy() -> None:
    mid = Decimal("100")
    costs = CostModel(
        commission_usd=Decimal("1"),
        spread_bps=Decimal("100"),
        slippage_bps=Decimal("100"),
        min_notional_usd=Decimal("1"),
        quantity_precision=6,
    )
    portfolio = Portfolio(cash=Decimal("100"), costs=costs)
    trade = portfolio.rebalance_to_weight(
        symbol="SPY",
        target_weight=Decimal("1"),
        price=mid,
        session_date=date(2024, 1, 2),
        reason="buy",
    )
    assert trade is not None
    half_spread = Decimal("0.5")
    slip = Decimal("1")
    assert trade.price == mid + half_spread + slip
    assert portfolio.cash == Decimal("100") - trade.quantity * trade.price - costs.commission_usd
    assert trade.spread_cost == trade.quantity * half_spread
    assert trade.slippage_cost == trade.quantity * slip
    marked = portfolio.cash + trade.quantity * mid
    economic = costs.commission_usd + trade.spread_cost + trade.slippage_cost
    assert marked == Decimal("100") - economic


def test_spread_and_slippage_are_charged_once_on_a_sell() -> None:
    costs = CostModel(
        commission_usd=Decimal("1"),
        spread_bps=Decimal("100"),
        slippage_bps=Decimal("100"),
        min_notional_usd=Decimal("1"),
        quantity_precision=6,
    )
    portfolio = Portfolio(cash=Decimal("0"), costs=costs, positions={"SPY": Decimal("1")})
    trade = portfolio.rebalance_to_weight(
        symbol="SPY",
        target_weight=Decimal("0"),
        price=Decimal("100"),
        session_date=date(2024, 1, 3),
        reason="sell",
    )
    assert trade is not None
    assert trade.price == Decimal("98.5")
    assert portfolio.cash == trade.quantity * trade.price - costs.commission_usd
    assert trade.spread_cost == Decimal("0.5")
    assert trade.slippage_cost == Decimal("1")


def test_market_open_follows_new_york_daylight_time() -> None:
    winter = datetime.fromisoformat(bar_open_timestamp(date(2024, 1, 2)))
    summer = datetime.fromisoformat(bar_open_timestamp(date(2024, 7, 1)))
    assert winter.astimezone(UTC).hour == 14
    assert winter.minute == 30
    assert summer.astimezone(UTC).hour == 13
    assert summer.minute == 30
    assert winter < summer
    assert is_early_close(date(2024, 7, 3))
    early = datetime.fromisoformat(bar_open_timestamp(date(2024, 7, 3)))
    assert early.astimezone(UTC).hour == 13


def test_sortino_uses_all_observations_against_zero() -> None:
    points = []
    equity = Decimal("100")
    returns = [Decimal("0.01"), Decimal("-0.02"), Decimal("0.01"), Decimal("-0.03")]
    for index, change in enumerate(returns):
        equity = equity * (Decimal("1") + change)
        points.append(
            EquityPoint(
                session_date=date(2024, 1, 2 + index),
                equity=equity,
                cash=equity,
                exposure=Decimal("0"),
                drawdown=Decimal("0"),
                window="test",
            )
        )
    metrics = compute_metrics(
        window="test",
        equity=points,
        trades=[],
        start_capital=Decimal("100"),
        opening_equity=Decimal("100"),
    )
    squares = sum(min(item, Decimal("0")) ** 2 for item in returns)
    downside = Decimal(str(sqrt(float(squares / Decimal(len(returns))))))
    annualized = downside * Decimal(str(sqrt(252)))
    mean = sum(returns, start=Decimal("0")) / Decimal(len(returns))
    expected = (mean * Decimal("252")) / annualized
    assert metrics.sortino is not None
    assert abs(metrics.sortino - expected) < Decimal("0.0000001")


def test_experiment_configuration_cannot_be_replaced(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path / "research.sqlite")
    row = {
        "experiment_id": "spy-tsmom-v1",
        "hypothesis_id": "H1",
        "title": "Original",
        "description": "Original",
        "citations": ["paper"],
        "config": {"lookback_sessions": 252},
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    store.upsert_experiment(row)
    store.upsert_experiment(row)
    with pytest.raises(ExperimentImmutableError):
        store.upsert_experiment({**row, "config": {"lookback_sessions": 20}})
    assert store.get_experiment("spy-tsmom-v1")["config"] == {"lookback_sessions": 252}


def test_missing_run_is_not_a_pass(tmp_path: Path) -> None:
    report = verify_run(
        99, research_path=tmp_path / "missing.sqlite", market_path=tmp_path / "none.sqlite"
    )
    assert report["verdict"] == "INVALID_ARTIFACT"
    assert report["verdict"] != "PASS"


def test_tools_reject_future_data_and_path_escape(tmp_path: Path) -> None:
    registry = ResearchToolRegistry(
        market_path=tmp_path / "market.sqlite",
        research_path=tmp_path / "research.sqlite",
        memo_root=tmp_path / "memos",
    )
    with pytest.raises(ToolError):
        registry.call(
            "read_market_data",
            {
                "symbol": "SPY",
                "feed": "sip",
                "start": "2024-01-02T00:00:00+00:00",
                "end": "2024-06-01T00:00:00+00:00",
                "as_of": "2024-02-01T00:00:00+00:00",
            },
        )
    with pytest.raises(ToolError):
        registry.call("save_research_memo", {"name": "../secret.md", "text": "no"})
    with pytest.raises(ToolError):
        registry.call("submit_order", {"symbol": "SPY"})
