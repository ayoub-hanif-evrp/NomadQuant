"""Load validated mark quotes for shadow valuation from the market store."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.store import MarketStore
from nomadquant.shadow.valuation import MarkQuote, PortfolioValuation, value_snapshot


def marks_for_holdings(
    market_path: str | Path,
    holdings: dict[str, Decimal],
    *,
    feed: str = "sip",
    as_of: datetime | None = None,
) -> dict[str, MarkQuote]:
    """Latest stored close per held symbol. Missing → omitted (valuation fails)."""
    if not holdings:
        return {}
    path = Path(market_path)
    if not path.exists():
        return {}
    market = MarketStore(path)
    now = as_of or datetime.now(UTC)
    marks: dict[str, MarkQuote] = {}
    for symbol, qty in holdings.items():
        if qty == 0:
            continue
        sym = str(symbol).upper()
        if not market.has_symbol(sym, feed):
            continue
        sessions = sorted(market.sessions(sym, feed))
        eligible = [s for s in sessions if modeled_available_at(s) <= now]
        if not eligible:
            continue
        session = eligible[-1]
        rows = list(market.session_ohlc(sym, feed, session, session))
        if not rows:
            continue
        _s, _o, _h, _l, close = rows[0]
        marks[sym] = MarkQuote(
            symbol=sym,
            price=Decimal(str(close)),
            as_of=modeled_available_at(session),
            feed=feed,
            source="market_store_close",
        )
    return marks


def value_forward_portfolio(
    snapshot: dict[str, Any],
    market_path: str | Path,
    *,
    feed: str = "sip",
    as_of: datetime | None = None,
) -> PortfolioValuation:
    marks = marks_for_holdings(
        market_path,
        dict(snapshot.get("holdings") or {}),
        feed=feed,
        as_of=as_of,
    )
    return value_snapshot(snapshot, marks)
