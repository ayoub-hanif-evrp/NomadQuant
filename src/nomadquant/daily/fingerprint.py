"""Bind a decision to the feed and closes used to compute it."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from nomadquant.config import Settings
from nomadquant.marketdata.validate import ADJUSTMENT, PROVIDER, TIMEFRAME

Prices = dict[str, dict[Any, Decimal]]
DATASET_ID = f"{PROVIDER}|{ADJUSTMENT}|{TIMEFRAME}"
FINGERPRINT_VERSION = "2"
_FEEDS = frozenset({"iex", "sip"})


def price_fingerprint(prices: Prices, *, feed: str) -> str:
    """Hash the feed, dataset, and exact closes. Another feed is a different input."""
    lines = [f"{FINGERPRINT_VERSION}|{feed}|{DATASET_ID}"]
    for symbol in sorted(prices):
        series = prices[symbol]
        for day in sorted(series):
            stamp = day.isoformat() if isinstance(day, date) else str(day)
            lines.append(f"{symbol}|{stamp}|{series[day]}")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def authoritative_disagreement(
    settings: Settings,
    prices: Prices,
    *,
    feed: str,
    decided_at: datetime,
    now: datetime,
) -> str | None:
    """Require every close on the decision's own feed, available when it was made.

    A second stored feed is not a conflict. A fingerprint match is not a
    substitute. Nothing is filled in from the other feed.
    """
    from nomadquant.marketdata.store import MarketStore

    if feed not in _FEEDS or not prices:
        return "unverified_market_data"
    if decided_at.tzinfo is None or now.tzinfo is None:
        return "unverified_market_data"
    store = MarketStore.open_readonly(settings.market_data_path)
    if store is None:
        return "unverified_market_data"
    clock = now.astimezone(UTC)
    decision = decided_at.astimezone(UTC)
    for symbol, series in prices.items():
        if not series:
            return "unverified_market_data"
        stored = _closes(store, symbol, feed)
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
            if available > decision:
                return "unavailable_at_decision"
    return None


def _closes(store: Any, symbol: str, feed: str) -> dict[str, tuple[Decimal, datetime]] | None:
    try:
        with store._connect() as connection:  # noqa: SLF001 — read stored closes only
            rows = connection.execute(
                """
                SELECT session_date, close, available_at FROM bars
                WHERE symbol = ? AND feed = ? AND provider = ? AND adjustment = ?
                  AND timeframe = ?
                """,
                (symbol, feed, PROVIDER, ADJUSTMENT, TIMEFRAME),
            ).fetchall()
    except Exception:  # noqa: BLE001
        return None
    found: dict[str, tuple[Decimal, datetime]] = {}
    for row in rows:
        key = str(row["session_date"])[:10]
        if key in found:
            return None
        available = datetime.fromisoformat(str(row["available_at"]))
        found[key] = (Decimal(str(row["close"])), available)
    return found
