"""Cash, holdings, and cost basis for one executed fill.

The execution price already contains spread and slippage. Cash changes by
the fill notional and commission only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from nomadquant.finance.execution import attribute_costs, execution_price
from nomadquant.research.models import CostModel

_ZERO = Decimal("0")


class MissingMark(Exception):
    """A nonzero holding has no usable mark. Equity must not become zero."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(f"INSUFFICIENT_DATA: missing mark for {symbol}")


@dataclass
class Book:
    cash: Decimal
    holdings: dict[str, Decimal] = field(default_factory=dict)
    cost_basis: dict[str, Decimal] = field(default_factory=dict)
    realized_pnl: Decimal = _ZERO
    attributed_costs: Decimal = _ZERO


@dataclass(frozen=True)
class FillResult:
    fill_price: Decimal
    quantity: Decimal
    side: str
    notional: Decimal
    commission: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    regulatory_fee: Decimal
    cash_delta: Decimal


def apply_fill(
    book: Book,
    *,
    symbol: str,
    side: str,
    quantity: Decimal,
    mid: Decimal,
    costs: CostModel,
) -> tuple[Book, FillResult]:
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity <= 0:
        raise ValueError("quantity must be a finite positive Decimal")
    if not isinstance(mid, Decimal) or not mid.is_finite():
        raise ValueError("mid must be a finite Decimal")
    price = execution_price(mid, costs, side=side)
    if not price.is_finite() or price <= 0:
        raise ValueError("execution price must stay finite and positive")
    costs_row = attribute_costs(mid, quantity, costs)
    notional = quantity * price
    commission = costs_row["commission"]
    symbol = symbol.upper()
    holdings = dict(book.holdings)
    basis = dict(book.cost_basis)
    cash = book.cash
    realized = book.realized_pnl
    if side == "buy":
        cash_delta = -(notional + commission)
        cash += cash_delta
        prev = holdings.get(symbol, _ZERO)
        prev_basis = basis.get(symbol, _ZERO)
        new_qty = prev + quantity
        basis[symbol] = ((prev_basis * prev) + notional) / new_qty if new_qty > 0 else _ZERO
        holdings[symbol] = new_qty
    elif side == "sell":
        held = holdings.get(symbol, _ZERO)
        if quantity > held:
            raise ValueError("sell quantity exceeds holdings")
        cash_delta = notional - commission
        cash += cash_delta
        prev_basis = basis.get(symbol, _ZERO)
        realized += (price - prev_basis) * quantity - commission
        remaining = held - quantity
        if remaining == 0:
            holdings.pop(symbol, None)
            basis.pop(symbol, None)
        else:
            holdings[symbol] = remaining
    else:
        raise ValueError(f"side must be buy or sell, got {side}")
    if cash < 0:
        raise ValueError("Fill would make cash negative.")
    attributed = (
        book.attributed_costs
        + costs_row["spread"]
        + costs_row["slippage"]
        + commission
        + costs_row["regulatory_fee"]
    )
    updated = Book(
        cash=cash,
        holdings=holdings,
        cost_basis=basis,
        realized_pnl=realized,
        attributed_costs=attributed,
    )
    result = FillResult(
        fill_price=price,
        quantity=quantity,
        side=side,
        notional=notional,
        commission=commission,
        spread_cost=costs_row["spread"],
        slippage_cost=costs_row["slippage"],
        regulatory_fee=costs_row["regulatory_fee"],
        cash_delta=cash_delta,
    )
    return updated, result


def mark_equity(book: Book, marks: dict[str, Decimal]) -> Decimal | None:
    """Equity = cash + quantity × mark. Missing marks return None."""
    equity = book.cash
    for symbol, qty in book.holdings.items():
        if qty == 0:
            continue
        price = marks.get(symbol)
        if price is None or price <= 0:
            return None
        equity += qty * price
    return equity


def unrealized_pnl(book: Book, marks: dict[str, Decimal]) -> Decimal | None:
    total = _ZERO
    for symbol, qty in book.holdings.items():
        if qty == 0:
            continue
        price = marks.get(symbol)
        if price is None or price <= 0:
            return None
        total += qty * price - qty * book.cost_basis.get(symbol, _ZERO)
    return total


ACCOUNTING_CONVENTION = (
    "Equity equals cash plus quantity times the mark. "
    "Unrealized equals quantity times the mark minus quantity times average cost. "
    "Average cost is the execution price, so spread and slippage are inside the price "
    "and are not subtracted again. "
    "A sell's realized increment is (execution price - average cost) times quantity, "
    "minus that sell's commission. "
    "A buy commission reduces cash and is subtracted once in the identity. "
    "Each sell, including a partial sell, is one win or loss observation. "
    "Cumulative realized P&L is not itself a win or a loss."
)


def economic_identity(
    book: Book,
    marks: dict[str, Decimal],
    *,
    starting: Decimal,
    cash_commissions: Decimal = _ZERO,
) -> dict[str, Decimal | str | None]:
    """Check starting + realized + unrealized - buy commissions == marked equity."""
    equity = mark_equity(book, marks)
    unrealized = unrealized_pnl(book, marks)
    if equity is None or unrealized is None:
        return {
            "status": "UNAVAILABLE",
            "equity": None,
            "expected": None,
            "residual": None,
            "unrealized": None,
            "realized": book.realized_pnl,
            "convention": ACCOUNTING_CONVENTION,
        }
    expected = starting + book.realized_pnl + unrealized - cash_commissions
    residual = equity - expected
    return {
        "status": "PASS" if residual == 0 else "FAIL",
        "equity": equity,
        "expected": expected,
        "residual": residual,
        "unrealized": unrealized,
        "realized": book.realized_pnl,
        "convention": ACCOUNTING_CONVENTION,
    }


def sell_observations(cumulative: list[Decimal]) -> list[Decimal]:
    """Realized increment of each sell. The previous cumulative is the baseline."""
    previous = _ZERO
    increments: list[Decimal] = []
    for total in cumulative:
        increments.append(total - previous)
        previous = total
    return increments


def max_drawdown(equities: list[Decimal | None]) -> Decimal | None:
    """Peak-to-trough drawdown. Missing marks are skipped and never treated as zero."""
    peak: Decimal | None = None
    worst = _ZERO
    seen = False
    for value in equities:
        if value is None:
            continue
        seen = True
        peak = value if peak is None else max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst if seen else None


def mark_sessions(
    sessions: list[date],
    closes: dict[date, Decimal],
    snapshots: list[tuple[date, Book]],
    *,
    symbol: str = "SPY",
    starting_cash: Decimal = Decimal("100"),
) -> list[dict[str, Decimal | str | None]]:
    """Mark the book at each session close after adopting fills dated on that session.

    A snapshot becomes effective on its session and stays in force afterward.
    A later session close is never used to value an earlier session.
    """
    ordered = sorted(snapshots, key=lambda item: item[0])
    current = Book(cash=starting_cash)
    cursor = 0
    points: list[dict[str, Decimal | str | None]] = []
    for session in sessions:
        while cursor < len(ordered) and ordered[cursor][0] <= session:
            current = ordered[cursor][1]
            cursor += 1
        close = closes.get(session)
        held = any(qty != 0 for qty in current.holdings.values())
        if held and (close is None or close <= 0):
            points.append(
                {
                    "session": str(session),
                    "status": "UNAVAILABLE",
                    "equity": None,
                    "unrealized": None,
                    "cash": current.cash,
                    "realized": current.realized_pnl,
                }
            )
            continue
        marks = {} if close is None else {symbol: close}
        equity = mark_equity(current, marks)
        unrealized = unrealized_pnl(current, marks)
        points.append(
            {
                "session": str(session),
                "status": "ok" if equity is not None else "UNAVAILABLE",
                "equity": equity,
                "unrealized": unrealized,
                "cash": current.cash,
                "realized": current.realized_pnl,
                "close": close,
            }
        )
    return points
