"""Display-only IEX snapshots. Never written to the SIP bar store or used by a strategy."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from nomadquant.config import Settings

SNAPSHOT_URL = "https://data.alpaca.markets/v2/stocks/snapshots"
FEED = "iex"
SYMBOLS = ("SPY", "QQQ")
CACHE_SECONDS = 15.0

_LABEL = (
    "IEX real-time quote from one exchange. Display only. "
    "The strategy uses SIP daily bars and never reads this price."
)

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "body": None}


def live_quotes(settings: Settings, *, opener: Any | None = None) -> dict[str, Any]:
    """Return a cached snapshot. One upstream request per 15 seconds at most."""
    with _lock:
        cached = _cache["body"]
        if cached is not None and time.monotonic() - float(_cache["at"]) < CACHE_SECONDS:
            return {**cached, "cached": True}
        body = _fetch(settings, opener)
        _cache["at"] = time.monotonic()
        _cache["body"] = body
        return {**body, "cached": False}


def clear_cache() -> None:
    with _lock:
        _cache["at"] = 0.0
        _cache["body"] = None


def _fetch(settings: Settings, opener: Any | None) -> dict[str, Any]:
    retrieved = datetime.now(UTC).isoformat()
    key = "" if settings.alpaca_api_key is None else settings.alpaca_api_key.get_secret_value()
    secret = (
        "" if settings.alpaca_api_secret is None else settings.alpaca_api_secret.get_secret_value()
    )
    base = {
        "feed": FEED,
        "label": _LABEL,
        "retrieved_at": retrieved,
        "used_by_strategy": False,
        "broker_orders": False,
    }
    if not key or not secret:
        return {**base, "status": "unavailable", "detail": "Alpaca keys are not set.", "quotes": {}}
    request = urllib.request.Request(  # noqa: S310 - fixed https host
        f"{SNAPSHOT_URL}?{urlencode({'symbols': ','.join(SYMBOLS), 'feed': FEED})}",
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        },
        method="GET",
    )
    client = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with client.open(request, timeout=8) as response:
            payload = json.loads(response.read(500_000))
    except urllib.error.HTTPError as exc:
        detail = "The IEX feed was refused." if exc.code in {401, 403} else f"HTTP {exc.code}"
        return {**base, "status": "unavailable", "detail": detail, "quotes": {}}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {**base, "status": "unavailable", "detail": type(exc).__name__, "quotes": {}}
    quotes = {symbol: _quote(payload.get(symbol)) for symbol in SYMBOLS}
    present = {symbol: quote for symbol, quote in quotes.items() if quote is not None}
    if not present:
        return {**base, "status": "unavailable", "detail": "No snapshot returned.", "quotes": {}}
    return {**base, "status": "ok", "detail": "", "quotes": present}


def _quote(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    trade = _section(raw, "latestTrade")
    daily = _section(raw, "dailyBar")
    prev = _section(raw, "prevDailyBar")
    price = _number(trade.get("p"))
    if price is None:
        return None
    prev_close = _number(prev.get("c"))
    change = None if not prev_close else price - prev_close
    return {
        "price": price,
        "trade_time": str(trade.get("t") or ""),
        "session_open": _number(daily.get("o")),
        "session_high": _number(daily.get("h")),
        "session_low": _number(daily.get("l")),
        "session_volume_iex": _number(daily.get("v")),
        "session_date": str(daily.get("t") or "")[:10],
        "previous_close": prev_close,
        "change": None if change is None else round(change, 4),
        "change_pct": (
            None if change is None or not prev_close else round(change / prev_close * 100, 3)
        ),
    }


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    return value if isinstance(value, dict) else {}


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
