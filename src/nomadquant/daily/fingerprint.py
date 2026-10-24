"""Bind a decision to the exact closes used to compute it."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from nomadquant.config import Settings

Prices = dict[str, dict[Any, Decimal]]


def price_fingerprint(prices: Prices) -> str:
    lines: list[str] = []
    for symbol in sorted(prices):
        series = prices[symbol]
        for day in sorted(series):
            stamp = day.isoformat() if isinstance(day, date) else str(day)
            lines.append(f"{symbol}|{stamp}|{series[day]}")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def authoritative_disagreement(settings: Settings, prices: Prices, *, now: datetime) -> str | None:
    """Require every supplied close to exist on exactly one stored feed.

    A fingerprint match is not a substitute. A missing bar, a second feed, or a
    bar that was not yet available is refused. Nothing is filled in.
    """
    from nomadquant.marketdata.store import MarketStore

    if not prices:
        return "unverified_market_data"
    store = MarketStore.open_readonly(settings.market_data_path)
    if store is None:
        return "unverified_market_data"
    clock = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    for symbol, series in prices.items():
        if not series:
            return "unverified_market_data"
        feeds = _feeds(store, symbol)
        if feeds is None:
            return "market_store_unreadable"
        if len(feeds) != 1:
            return "ambiguous_market_feed" if feeds else "unverified_market_data"
        stored = _closes(store, symbol, feeds[0])
        if stored is None:
            return "market_store_unreadable"
        for day, close in series.items():
            key = day.isoformat() if isinstance(day, date) else str(day)[:10]
            official = stored.get(key)
            if official is None:
                return "unverified_market_data"
            if official[0] != close:
                return "authoritative_price_mismatch"
            available = official[1]
            if available.tzinfo is None or available > clock:
                return "future_market_data"
    return None


def _feeds(store: Any, symbol: str) -> list[str] | None:
    found: list[str] = []
    for feed in ("iex", "sip"):
        try:
            if store.has_symbol(symbol, feed):
                found.append(feed)
        except Exception:  # noqa: BLE001 — an unreadable store is not permission
            return None
    return found


def _closes(store: Any, symbol: str, feed: str) -> dict[str, tuple[Decimal, datetime]] | None:
    try:
        with store._connect() as connection:  # noqa: SLF001 — read stored closes only
            rows = connection.execute(
                """
                SELECT session_date, close, available_at FROM bars
                WHERE symbol = ? AND feed = ?
                """,
                (symbol, feed),
            ).fetchall()
    except Exception:  # noqa: BLE001
        return None
    found: dict[str, tuple[Decimal, datetime]] = {}
    for row in rows:
        available = datetime.fromisoformat(str(row["available_at"]))
        found[str(row["session_date"])[:10]] = (Decimal(str(row["close"])), available)
    return found
