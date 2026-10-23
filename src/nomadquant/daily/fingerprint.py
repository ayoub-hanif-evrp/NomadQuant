"""Bind a decision to the exact closes used to compute it."""

from __future__ import annotations

import hashlib
from datetime import date
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


def authoritative_disagreement(settings: Settings, prices: Prices) -> str | None:
    """Compare supplied closes with a local market store when that store has bars.

    An empty store cannot confirm the series. A stored close that differs refuses
    the order. This does not invent a bar the store does not contain.
    """
    from nomadquant.marketdata.store import MarketStore

    store = MarketStore.open_readonly(settings.market_data_path)
    if store is None:
        return None
    for symbol, series in prices.items():
        feed = _feed(store, symbol)
        if feed is None:
            continue
        stored = _closes(store, symbol, feed)
        if stored is None:
            return "market_store_unreadable"
        for day, close in series.items():
            key = day.isoformat() if isinstance(day, date) else str(day)[:10]
            official = stored.get(key)
            if official is not None and official != close:
                return "authoritative_price_mismatch"
    return None


def _feed(store: Any, symbol: str) -> str | None:
    for feed in ("iex", "sip"):
        try:
            if store.has_symbol(symbol, feed):
                return feed
        except Exception:  # noqa: BLE001 — an unreadable store is not permission
            return None
    return None


def _closes(store: Any, symbol: str, feed: str) -> dict[str, Decimal] | None:
    try:
        with store._connect() as connection:  # noqa: SLF001 — read the stored close, nothing else
            rows = connection.execute(
                """
                SELECT session_date, close FROM bars
                WHERE symbol = ? AND feed = ?
                """,
                (symbol, feed),
            ).fetchall()
    except Exception:  # noqa: BLE001
        return None
    found: dict[str, Decimal] = {}
    for row in rows:
        found[str(row["session_date"])[:10]] = Decimal(str(row["close"]))
    return found
