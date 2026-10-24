"""Allocated $100 portfolio. Each broker fill changes cash and quantity once."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from nomadquant.daily.fills import fill_lots

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
_TERMINAL = frozenset({"filled", "canceled", "cancelled", "rejected", "expired"})


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


def _deduped(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one row per client id. A repeated observation must not apply twice."""
    chosen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, row in enumerate(orders):
        key = str(row.get("client_order_id") or f"row-{index}")
        previous = chosen.get(key)
        if previous is None:
            chosen[key] = row
            order.append(key)
            continue
        previous_qty = _money(previous.get("filled_qty")) or Decimal("0")
        current_qty = _money(row.get("filled_qty")) or Decimal("0")
        if current_qty >= previous_qty:
            chosen[key] = row
    rows = [chosen[key] for key in order]
    rows.sort(
        key=lambda row: (str(row.get("created_at") or ""), 0 if row.get("side") == "buy" else 1)
    )
    return rows


def build_portfolio(
    orders: list[dict[str, Any]],
    marks: dict[str, Decimal] | None = None,
    *,
    session: date | None = None,
    executions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return allocated cash, cost basis, and strategy P&L.

    Fills come from execution events. An order's ``created_at`` is not a fill
    time. A sell without an execution timestamp leaves today's P&L unverified.
    A missing mark leaves valuation unavailable. A cancelled order keeps any
    shares that actually filled.
    """
    rows = _deduped(orders)
    lots, disputed = fill_lots(rows, [] if executions is None else executions)
    cash = ALLOCATION
    reserved = Decimal("0")
    realized = Decimal("0")
    realized_today = Decimal("0")
    today_known = session is not None
    connectivity_qty = Decimal("0")
    connectivity_cost = Decimal("0")
    quantity: dict[str, Decimal] = {}
    cost: dict[str, Decimal] = {}
    sell_reserved: dict[str, Decimal] = {}
    uncertain = False
    for lot in lots:
        purpose = str(lot.get("purpose") or "")
        side = str(lot.get("side") or "")
        symbol = str(lot.get("symbol") or "")
        filled = _money(lot.get("qty")) or Decimal("0")
        price = _money(lot.get("price"))
        if purpose == "connectivity":
            if side == "buy" and filled > 0 and price is not None and price > 0:
                connectivity_qty += filled
                connectivity_cost += filled * price
                cash -= filled * price
            else:
                uncertain = True
            continue
        if side == "sell":
            owned = quantity.get(symbol, Decimal("0"))
            basis = cost.get(symbol, Decimal("0"))
            if filled > owned or owned <= 0 or price is None or price <= 0:
                disputed = True
                continue
            removed = basis * filled / owned
            quantity[symbol] = owned - filled
            cost[symbol] = basis - removed
            gain = filled * price - removed
            cash += filled * price
            realized += gain
            traded = _session_day(lot.get("executed_at"))
            if traded is None:
                today_known = False
            elif session is not None and traded == session:
                realized_today += gain
            continue
        if side != "buy" or price is None or price <= 0 or filled <= 0:
            uncertain = True
            continue
        quantity[symbol] = quantity.get(symbol, Decimal("0")) + filled
        cost[symbol] = cost.get(symbol, Decimal("0")) + filled * price
        cash -= filled * price
    for row in rows:
        status = str(row.get("broker_status") or "")
        side = str(row.get("side") or "")
        symbol = str(row.get("symbol") or "")
        filled = _money(row.get("filled_qty")) or Decimal("0")
        price = _money(row.get("filled_avg_price"))
        notional = _money(row.get("notional_usd")) or Decimal("0")
        if status not in _OPEN and status not in _TERMINAL:
            uncertain = True
        if status == "unknown":
            uncertain = True
        if status not in _OPEN:
            continue
        if side == "sell":
            remaining = _money(row.get("remaining_qty"))
            if remaining is None:
                uncertain = True
            elif remaining > 0:
                sell_reserved[symbol] = sell_reserved.get(symbol, Decimal("0")) + remaining
            continue
        if side != "buy":
            uncertain = True
            continue
        spent = filled * price if filled > 0 and price is not None and price > 0 else Decimal("0")
        reserved += max(Decimal("0"), notional - spent)
        cash -= max(Decimal("0"), notional - spent)
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
    connectivity_value = Decimal("0")
    if connectivity_qty > 0:
        mark = None if marks is None else marks.get("SPY")
        if mark is None or mark <= 0:
            missing_mark = True
        else:
            connectivity_value = connectivity_qty * mark
    if missing_mark or disputed:
        strategy_pnl = None
        equity = None
        valuation = "unavailable"
    else:
        strategy_pnl = realized + unrealized
        equity = cash + reserved + market_value + connectivity_value
        valuation = "marked"
    readiness = "disputed" if disputed else "uncertain" if uncertain or missing_mark else "ready"
    return {
        "allocated_capital_usd": format(ALLOCATION, "f"),
        "available_cash_usd": format(cash, "f"),
        "reserved_cash_usd": format(reserved, "f"),
        "realized_pnl_usd": format(realized, "f"),
        "realized_today_usd": None
        if session is None or not today_known
        else format(realized_today, "f"),
        "unrealized_pnl_usd": None if strategy_pnl is None else format(unrealized, "f"),
        "strategy_pnl_usd": None if strategy_pnl is None else format(strategy_pnl, "f"),
        "equity_usd": None if equity is None else format(equity, "f"),
        "valuation": valuation,
        "strategy_qty": {key: format(value, "f") for key, value in quantity.items() if value > 0},
        "strategy_cost_usd": {key: format(value, "f") for key, value in cost.items() if value > 0},
        "reserved_sell_qty": {
            key: format(value, "f") for key, value in sell_reserved.items() if value > 0
        },
        "connectivity_qty": format(connectivity_qty, "f"),
        "connectivity_cost_usd": format(connectivity_cost, "f"),
        "connectivity_counts_as_strategy_pnl": False,
        "marks_complete": readiness == "ready",
        "disputed": disputed,
        "readiness": readiness,
        "loss_stop": bool(strategy_pnl is not None and strategy_pnl <= -STRATEGY_LOSS_STOP),
    }


def _session_day(value: object) -> date | None:
    """Assign a New York session only from a timezone-aware execution timestamp."""
    if not isinstance(value, str) or not value:
        return None
    try:
        executed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if executed.tzinfo is None:
        return None
    return executed.astimezone(ZoneInfo("America/New_York")).date()
