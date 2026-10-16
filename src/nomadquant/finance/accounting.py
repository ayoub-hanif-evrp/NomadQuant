"""Cash, holdings, and cost basis for one executed fill.

The execution price already contains spread and slippage. Cash changes by
the fill notional and commission only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    price = execution_price(mid, costs, side=side)
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
