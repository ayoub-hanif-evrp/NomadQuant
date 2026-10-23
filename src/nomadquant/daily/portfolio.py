"""Allocated $100 portfolio. Broker fills are the quantities; buying power is ignored."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

ALLOCATION = Decimal("100")
STRATEGY_LOSS_STOP = Decimal("20")
_OPEN = frozenset(
    {
        "prepared",
        "submitted",
        "unknown",
        "accepted",
        "partial",
        "pending_new",
        "new",
        "accepted_for_bidding",
    }
)


def _money(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None
    if not parsed.is_finite():
        return None
    return parsed


def build_portfolio(
    orders: list[dict[str, Any]],
    marks: dict[str, Decimal] | None = None,
) -> dict[str, Any]:
    """Return allocated cash, cost basis, and strategy P&L.

    A missing mark on an open strategy or connectivity quantity blocks new risk
    decisions. It is not treated as a zero price or as a profit.
    """
    cash = ALLOCATION
    reserved = Decimal("0")
    realized = Decimal("0")
    connectivity_qty = Decimal("0")
    connectivity_cost = Decimal("0")
    quantity: dict[str, Decimal] = {}
    cost: dict[str, Decimal] = {}
    disputed = False
    for row in orders:
        purpose = str(row.get("purpose") or "")
        status = str(row.get("broker_status") or "")
        side = str(row.get("side") or "")
        symbol = str(row.get("symbol") or "")
        filled = _money(row.get("filled_qty")) or Decimal("0")
        price = _money(row.get("filled_avg_price"))
        notional = _money(row.get("notional_usd")) or Decimal("0")
        if purpose == "connectivity":
            if side == "buy" and status == "filled" and filled > 0 and price is not None:
                connectivity_qty += filled
                spent = filled * price
                connectivity_cost += spent
                cash -= spent
            elif side == "buy" and status in _OPEN:
                reserved += notional
                cash -= notional
            continue
        if side == "sell" and status == "filled" and filled > 0 and price is not None:
            owned = quantity.get(symbol, Decimal("0"))
            basis = cost.get(symbol, Decimal("0"))
            if filled > owned or owned <= 0:
                disputed = True
                continue
            removed = basis * filled / owned
            quantity[symbol] = owned - filled
            cost[symbol] = basis - removed
            cash += filled * price
            realized += filled * price - removed
            continue
        if side != "buy":
            continue
        spent = filled * price if filled > 0 and price is not None else Decimal("0")
        if status == "filled" and spent > 0:
            quantity[symbol] = quantity.get(symbol, Decimal("0")) + filled
            cost[symbol] = cost.get(symbol, Decimal("0")) + spent
            cash -= spent
        elif status in _OPEN:
            remainder = max(Decimal("0"), notional - spent)
            reserved += remainder
            cash -= spent + remainder
            if spent > 0:
                quantity[symbol] = quantity.get(symbol, Decimal("0")) + filled
                cost[symbol] = cost.get(symbol, Decimal("0")) + spent
    unrealized = Decimal("0")
    market_value = Decimal("0")
    missing_mark = False
    for symbol, owned in quantity.items():
        if owned <= 0:
            continue
        mark = None if marks is None else marks.get(symbol)
        if mark is None or mark <= 0:
            missing_mark = True
            continue
        market_value += owned * mark
        unrealized += owned * mark - cost.get(symbol, Decimal("0"))
    connectivity_value = connectivity_cost
    if connectivity_qty > 0:
        mark = None if marks is None else marks.get("SPY")
        if mark is None or mark <= 0:
            missing_mark = True
        else:
            connectivity_value = connectivity_qty * mark
    strategy_pnl = None if missing_mark else realized + unrealized
    equity = cash + reserved + market_value
    if not missing_mark:
        equity += connectivity_value
    else:
        equity += connectivity_cost
    return {
        "allocated_capital_usd": format(ALLOCATION, "f"),
        "available_cash_usd": format(cash, "f"),
        "reserved_cash_usd": format(reserved, "f"),
        "realized_pnl_usd": format(realized, "f"),
        "unrealized_pnl_usd": None if missing_mark else format(unrealized, "f"),
        "strategy_pnl_usd": None if strategy_pnl is None else format(strategy_pnl, "f"),
        "equity_usd": format(equity, "f"),
        "strategy_qty": {key: format(value, "f") for key, value in quantity.items() if value > 0},
        "strategy_cost_usd": {key: format(value, "f") for key, value in cost.items() if value > 0},
        "connectivity_qty": format(connectivity_qty, "f"),
        "connectivity_cost_usd": format(connectivity_cost, "f"),
        "connectivity_counts_as_strategy_pnl": False,
        "marks_complete": not missing_mark and not disputed,
        "disputed": disputed,
        "loss_stop": bool(strategy_pnl is not None and strategy_pnl <= -STRATEGY_LOSS_STOP),
    }
