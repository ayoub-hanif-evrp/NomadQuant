"""Hand-calculated fill prices. These numbers are not produced by either engine."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from nomadquant.finance.accounting import Book, MissingMark, apply_fill, mark_equity
from nomadquant.finance.execution import (
    CONVENTION_ID,
    legacy_shadow_execution_price,
)
from nomadquant.research.models import CostModel
from nomadquant.research.portfolio import Portfolio
from nomadquant.research.signals import momentum_return, target_from_momentum
from nomadquant.shadow.cycle import _simulate_fill

_COSTS = CostModel(
    commission_usd=Decimal("0"),
    spread_bps=Decimal("1"),
    slippage_bps=Decimal("1"),
    min_notional_usd=Decimal("1"),
    quantity_precision=6,
)


def test_research_and_shadow_use_the_same_full_slippage_price() -> None:
    """$100 mid, 1 bp spread, 1 bp slippage, 1 share, commission 0.

    Half-spread is $0.005. Full slippage is $0.010.
    Buy is $100.015. Sell is $99.985.
    """
    mid = Decimal("100")
    research_buy = Portfolio(cash=Decimal("200"), costs=_COSTS)._fill_price(mid, buy=True)
    research_sell = Portfolio(cash=Decimal("0"), costs=_COSTS)._fill_price(mid, buy=False)
    before = {
        "cash_usd": Decimal("200"),
        "holdings": {},
        "cost_basis": {},
        "realized_pnl_usd": Decimal("0"),
        "total_costs_usd": Decimal("0"),
        "peak_equity_usd": Decimal("200"),
    }
    _after_buy, buy_meta = _simulate_fill(before, "buy", Decimal("1"), mid, _COSTS)
    sell_book = {
        **before,
        "cash_usd": Decimal("0"),
        "holdings": {"SPY": Decimal("1")},
        "cost_basis": {"SPY": Decimal("100")},
    }
    _after_sell, sell_meta = _simulate_fill(sell_book, "sell", Decimal("1"), mid, _COSTS)
    assert research_buy == Decimal("100.015")
    assert Decimal(buy_meta["fill_price"]) == Decimal("100.015")
    assert research_sell == Decimal("99.985")
    assert Decimal(sell_meta["fill_price"]) == Decimal("99.985")
    assert buy_meta["execution_convention"] == CONVENTION_ID
    legacy = legacy_shadow_execution_price(mid, _COSTS, side="buy")
    assert legacy == Decimal("100.01")
    assert legacy != research_buy


def test_half_share_buy_and_sell_match_the_hand_calculation() -> None:
    """0.5 share at a $100 mid, then a full sale at a $110 mid. Commission is 0."""
    qty = Decimal("0.5")
    buy_mid = Decimal("100")
    sell_mid = Decimal("110")
    book, bought = apply_fill(
        Book(cash=Decimal("100")),
        symbol="SPY",
        side="buy",
        quantity=qty,
        mid=buy_mid,
        costs=_COSTS,
    )
    assert bought.fill_price == Decimal("100.015")
    assert bought.notional == Decimal("50.0075")
    assert bought.cash_delta == Decimal("-50.0075")
    assert book.cash == Decimal("49.9925")
    assert book.holdings["SPY"] == qty
    assert book.cost_basis["SPY"] == Decimal("100.015")
    assert book.attributed_costs == Decimal("0.0075")
    assert book.cash == Decimal("100") + bought.cash_delta

    research = Portfolio(cash=Decimal("100"), costs=_COSTS)
    trade = research._buy("SPY", bought.notional, buy_mid, date(2024, 1, 2), "parity")
    assert trade is not None
    assert trade.price == bought.fill_price
    assert research.cash == book.cash
    assert research.positions["SPY"] == book.holdings["SPY"]
    assert research.cost_basis["SPY"] == book.cost_basis["SPY"]

    shadow_after, shadow_meta = _simulate_fill(
        {
            "cash_usd": Decimal("100"),
            "holdings": {},
            "cost_basis": {},
            "realized_pnl_usd": Decimal("0"),
            "total_costs_usd": Decimal("0"),
            "peak_equity_usd": Decimal("100"),
        },
        "buy",
        qty,
        buy_mid,
        _COSTS,
    )
    assert Decimal(shadow_meta["fill_price"]) == bought.fill_price
    assert shadow_after["cash_usd"] == research.cash
    assert shadow_after["holdings"]["SPY"] == research.positions["SPY"]
    assert shadow_after["cost_basis"]["SPY"] == research.cost_basis["SPY"]

    sold_book, sold = apply_fill(
        book, symbol="SPY", side="sell", quantity=qty, mid=sell_mid, costs=_COSTS
    )
    assert sold.fill_price == Decimal("109.9835")
    assert sold.notional == Decimal("54.99175")
    assert sold_book.cash == Decimal("104.98425")
    assert sold_book.holdings == {}
    assert sold_book.realized_pnl == Decimal("4.98425")
    assert "SPY" not in sold_book.cost_basis
    marked = mark_equity(book, {"SPY": sell_mid})
    assert marked == book.cash + qty * sell_mid
    assert mark_equity(book, {}) is None


def test_missing_mark_does_not_value_a_holding_at_zero() -> None:
    portfolio = Portfolio(cash=Decimal("50"), costs=_COSTS, positions={"SPY": Decimal("1")})
    with pytest.raises(MissingMark):
        portfolio.market_value({})


def test_unavailable_momentum_is_not_a_cash_target() -> None:
    with pytest.raises(ValueError, match="INSUFFICIENT_DATA"):
        target_from_momentum(None)
    assert target_from_momentum(Decimal("0")) == Decimal("0")
    assert target_from_momentum(Decimal("-0.2")) == Decimal("0")
    assert target_from_momentum(Decimal("0.2")) == Decimal("1")


def test_registered_momentum_needs_274_sessions_and_252_intervals() -> None:
    start = date(2018, 1, 2)
    short = [start + timedelta(days=index) for index in range(273)]
    closes = {session: Decimal("100") + index for index, session in enumerate(short)}
    assert momentum_return(closes, short, short[-1], 252, 21) is None
    sessions = [start + timedelta(days=index) for index in range(274)]
    closes = {session: Decimal("100") for session in sessions}
    closes[sessions[0]] = Decimal("80")
    closes[sessions[252]] = Decimal("100")
    value = momentum_return(closes, sessions, sessions[-1], 252, 21)
    assert value == Decimal("100") / Decimal("80") - 1
