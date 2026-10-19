"""Golden portfolio cases for the simulation lab's accounting identity."""

from datetime import date
from decimal import Decimal

from nomadquant.finance.accounting import (
    Book,
    apply_fill,
    economic_identity,
    mark_sessions,
    max_drawdown,
    sell_observations,
)
from nomadquant.lab.runner import _event, _summary
from nomadquant.research.models import CostModel

_FREE = CostModel(
    commission_usd=Decimal("0"),
    spread_bps=Decimal("0"),
    slippage_bps=Decimal("0"),
    min_notional_usd=Decimal("1"),
    quantity_precision=6,
)
_START = Decimal("100")


def _buy(book: Book, mid: Decimal, quantity: Decimal, costs: CostModel = _FREE) -> Book:
    updated, _fill = apply_fill(
        book, symbol="SPY", side="buy", quantity=quantity, mid=mid, costs=costs
    )
    return updated


def _sell(book: Book, mid: Decimal, quantity: Decimal, costs: CostModel = _FREE) -> Book:
    updated, _fill = apply_fill(
        book, symbol="SPY", side="sell", quantity=quantity, mid=mid, costs=costs
    )
    return updated


def _check(book: Book, mark: Decimal, *, commissions: Decimal = Decimal("0")) -> None:
    identity = economic_identity(book, {"SPY": mark}, starting=_START, cash_commissions=commissions)
    assert identity["status"] == "PASS"
    assert identity["residual"] == 0


def test_buy_then_price_rises() -> None:
    book = _buy(Book(cash=_START), Decimal("40"), Decimal("1"))
    _check(book, Decimal("50"))
    assert economic_identity(book, {"SPY": Decimal("50")}, starting=_START)[
        "unrealized"
    ] == Decimal("10")


def test_buy_then_price_falls() -> None:
    book = _buy(Book(cash=_START), Decimal("40"), Decimal("1"))
    _check(book, Decimal("30"))
    assert economic_identity(book, {"SPY": Decimal("30")}, starting=_START)["equity"] == Decimal(
        "90"
    )


def test_sell_at_a_profit() -> None:
    book = _sell(_buy(Book(cash=_START), Decimal("40"), Decimal("1")), Decimal("50"), Decimal("1"))
    _check(book, Decimal("50"))
    assert book.realized_pnl == Decimal("10")
    assert book.holdings == {}


def test_sell_at_a_loss_after_a_profitable_exit() -> None:
    first = _sell(_buy(Book(cash=_START), Decimal("40"), Decimal("1")), Decimal("50"), Decimal("1"))
    second = _sell(_buy(first, Decimal("40"), Decimal("1")), Decimal("30"), Decimal("1"))
    _check(second, Decimal("30"))
    increments = sell_observations([first.realized_pnl, second.realized_pnl])
    assert increments == [Decimal("10"), Decimal("-10")]
    assert second.realized_pnl == 0


def test_partial_sell_is_its_own_observation() -> None:
    bought = _buy(Book(cash=_START), Decimal("40"), Decimal("2"))
    sold = _sell(bought, Decimal("50"), Decimal("1"))
    _check(sold, Decimal("50"))
    assert sold.holdings["SPY"] == Decimal("1")
    assert sell_observations([sold.realized_pnl]) == [Decimal("10")]


def test_second_sell_can_lose_while_cumulative_realized_stays_positive() -> None:
    bought = _buy(Book(cash=_START), Decimal("40"), Decimal("2"))
    first = _sell(bought, Decimal("55"), Decimal("1"))
    second = _sell(first, Decimal("35"), Decimal("1"))
    increments = sell_observations([first.realized_pnl, second.realized_pnl])
    assert increments == [Decimal("15"), Decimal("-5")]
    assert second.realized_pnl == Decimal("10")
    assert sum(1 for item in increments if item > 0) == 1
    assert sum(1 for item in increments if item < 0) == 1
    _check(second, Decimal("35"))


def test_buy_commission_is_subtracted_once() -> None:
    costs = CostModel(
        commission_usd=Decimal("1"),
        spread_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        min_notional_usd=Decimal("1"),
        quantity_precision=6,
    )
    book = _buy(Book(cash=_START), Decimal("40"), Decimal("1"), costs)
    identity = economic_identity(
        book, {"SPY": Decimal("40")}, starting=_START, cash_commissions=Decimal("1")
    )
    assert identity["status"] == "PASS"
    assert identity["equity"] == Decimal("99")


def test_risk_rejection_does_not_replace_the_portfolio() -> None:
    summary = _summary(
        [
            _position_event("150", authoritative=True),
            _position_event("100", authoritative=False, decision="risk_rejected"),
        ],
        "SYNTHETIC MECHANICS TEST",
        [],
    )
    assert summary["ending_usd"] == "150"


def test_duplicate_event_does_not_replace_the_portfolio() -> None:
    summary = _summary(
        [
            _position_event("150", authoritative=True),
            _position_event("50", authoritative=False, decision="duplicate_prevented"),
        ],
        "HISTORICAL SIMULATION",
        [],
    )
    assert summary["ending_usd"] == "150"


def test_missing_mark_is_unavailable() -> None:
    day = date(2024, 1, 2)
    book = Book(
        cash=Decimal("60"), holdings={"SPY": Decimal("1")}, cost_basis={"SPY": Decimal("40")}
    )
    points = mark_sessions([day], {}, [(day, book)])
    assert points[0]["status"] == "UNAVAILABLE"
    assert points[0]["equity"] is None
    assert max_drawdown([None]) is None


def test_daily_drawdown_between_rebalances_is_not_the_sparse_event_drawdown() -> None:
    first, dip, last = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)
    book = Book(
        cash=Decimal("0"), holdings={"SPY": Decimal("1")}, cost_basis={"SPY": Decimal("100")}
    )
    closes = {first: Decimal("100"), dip: Decimal("80"), last: Decimal("100")}
    points = mark_sessions([first, dip, last], closes, [(first, book)])
    equities = [item["equity"] for item in points]
    assert equities == [Decimal("100"), Decimal("80"), Decimal("100")]
    assert max_drawdown([Decimal("100"), Decimal("100")]) == 0
    assert max_drawdown(equities) == Decimal("0.2")  # type: ignore[arg-type]


def test_filled_event_is_marked_with_the_fill_session_close() -> None:
    signal, fill = date(2024, 1, 2), date(2024, 1, 3)
    event = _event(
        {
            "status": "filled",
            "intent": "buy",
            "signal_session": signal.isoformat(),
            "fill_session": fill.isoformat(),
            "fill_side": "buy",
            "fill_price": "40",
            "fill_qty": "1",
            "ledger_after": {
                "cash_usd": "60",
                "holdings": {"SPY": "1"},
                "cost_basis": {"SPY": "40"},
                "realized_pnl_usd": "0",
            },
        },
        "HISTORICAL SIMULATION",
        {signal: Decimal("39"), fill: Decimal("50")},
    )
    assert event["valuation_session"] == fill.isoformat()
    assert event["valuation_price"] == "50"
    assert event["equity_usd"] == "110"
    assert event["authoritative"] is True


def _position_event(
    equity: str, *, authoritative: bool, decision: str = "buy"
) -> dict[str, object]:
    return {
        "authoritative": authoritative,
        "status": "filled" if authoritative else decision,
        "side": "buy" if authoritative else None,
        "decision": decision,
        "cash_usd": equity,
        "holdings": {},
        "cost_basis": {},
        "equity_usd": equity,
        "unrealized_pnl_usd": "0",
        "realized_pnl_usd": "0",
        "valuation_status": "ok",
        "costs_usd": "0",
    }
