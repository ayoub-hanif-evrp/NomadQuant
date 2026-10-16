"""Authoritative shadow portfolio valuation. Never invents equity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

ValuationStatus = Literal["ok", "stale", "valuation_unavailable"]

_ZERO = Decimal("0")


@dataclass(frozen=True)
class MarkQuote:
    symbol: str
    price: Decimal
    as_of: datetime
    feed: str
    source: str = "market_store"


@dataclass(frozen=True)
class PositionValue:
    symbol: str
    quantity: Decimal
    mark_price: Decimal
    market_value_usd: Decimal
    cost_basis_usd: Decimal
    unrealized_pnl_usd: Decimal
    mark_as_of: datetime
    feed: str


@dataclass(frozen=True)
class PortfolioValuation:
    status: ValuationStatus
    cash_usd: Decimal
    reserved_cash_usd: Decimal
    available_cash_usd: Decimal
    positions: tuple[PositionValue, ...]
    equity_usd: Decimal | None
    exposure_usd: Decimal | None
    exposure_fraction: Decimal | None
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal | None
    total_costs_usd: Decimal
    starting_capital_usd: Decimal
    valuation_as_of: datetime | None
    reason: str
    ledger_version: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cash_usd": str(self.cash_usd),
            "reserved_cash_usd": str(self.reserved_cash_usd),
            "available_cash_usd": str(self.available_cash_usd),
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": str(p.quantity),
                    "mark_price": str(p.mark_price),
                    "market_value_usd": str(p.market_value_usd),
                    "cost_basis_usd": str(p.cost_basis_usd),
                    "unrealized_pnl_usd": str(p.unrealized_pnl_usd),
                    "mark_as_of": p.mark_as_of.isoformat(),
                    "feed": p.feed,
                }
                for p in self.positions
            ],
            "equity_usd": None if self.equity_usd is None else str(self.equity_usd),
            "exposure_usd": None if self.exposure_usd is None else str(self.exposure_usd),
            "exposure_fraction": (
                None if self.exposure_fraction is None else str(self.exposure_fraction)
            ),
            "realized_pnl_usd": str(self.realized_pnl_usd),
            "unrealized_pnl_usd": (
                None if self.unrealized_pnl_usd is None else str(self.unrealized_pnl_usd)
            ),
            "total_costs_usd": str(self.total_costs_usd),
            "starting_capital_usd": str(self.starting_capital_usd),
            "valuation_as_of": (
                None if self.valuation_as_of is None else self.valuation_as_of.isoformat()
            ),
            "reason": self.reason,
            "ledger_version": self.ledger_version,
            "note": (
                "Equity = cash + sum(quantity × validated mark). "
                "Reserved cash is part of cash, not added twice. "
                "Not Alpaca paper equity."
            ),
        }


def value_snapshot(
    snapshot: dict[str, Any],
    marks: dict[str, MarkQuote],
    *,
    capital_usd: Decimal = Decimal("100"),
) -> PortfolioValuation:
    """Mark holdings with validated prices. Missing marks → valuation_unavailable."""
    cash = Decimal(str(snapshot["cash_usd"]))
    reserved = Decimal(str(snapshot.get("reserved_cash_usd", "0")))
    holdings: dict[str, Decimal] = {
        str(k).upper(): Decimal(str(v)) for k, v in dict(snapshot.get("holdings") or {}).items()
    }
    basis_map: dict[str, Decimal] = {
        str(k).upper(): Decimal(str(v)) for k, v in dict(snapshot.get("cost_basis") or {}).items()
    }
    realized = Decimal(str(snapshot.get("realized_pnl_usd", "0")))
    costs = Decimal(str(snapshot.get("total_costs_usd", "0")))
    version = int(snapshot.get("version") or 0)

    positions: list[PositionValue] = []
    exposure = _ZERO
    unrealized = _ZERO
    latest: datetime | None = None
    missing: list[str] = []

    for symbol, qty in sorted(holdings.items()):
        if qty == 0:
            continue
        mark = marks.get(symbol)
        if mark is None or mark.price <= 0 or not mark.price.is_finite():
            missing.append(symbol)
            continue
        if mark.as_of.tzinfo is None:
            missing.append(symbol)
            continue
        mv = qty * mark.price
        cb = basis_map.get(symbol, _ZERO) * qty
        upnl = mv - cb
        positions.append(
            PositionValue(
                symbol=symbol,
                quantity=qty,
                mark_price=mark.price,
                market_value_usd=mv,
                cost_basis_usd=cb,
                unrealized_pnl_usd=upnl,
                mark_as_of=mark.as_of,
                feed=mark.feed,
            )
        )
        exposure += mv
        unrealized += upnl
        latest = mark.as_of if latest is None else max(latest, mark.as_of)

    if missing:
        return PortfolioValuation(
            status="valuation_unavailable",
            cash_usd=cash,
            reserved_cash_usd=reserved,
            available_cash_usd=cash - reserved,
            positions=tuple(positions),
            equity_usd=None,
            exposure_usd=None,
            exposure_fraction=None,
            realized_pnl_usd=realized,
            unrealized_pnl_usd=None,
            total_costs_usd=costs,
            starting_capital_usd=capital_usd,
            valuation_as_of=None,
            reason="Missing or invalid marks for: " + ", ".join(missing),
            ledger_version=version,
        )

    equity = cash + exposure
    frac = (exposure / equity) if equity > 0 else _ZERO
    return PortfolioValuation(
        status="ok",
        cash_usd=cash,
        reserved_cash_usd=reserved,
        available_cash_usd=cash - reserved,
        positions=tuple(positions),
        equity_usd=equity,
        exposure_usd=exposure,
        exposure_fraction=frac,
        realized_pnl_usd=realized,
        unrealized_pnl_usd=unrealized,
        total_costs_usd=costs,
        starting_capital_usd=capital_usd,
        valuation_as_of=latest,
        reason="Valued with validated mark prices.",
        ledger_version=version,
    )
