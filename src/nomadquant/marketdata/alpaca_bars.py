"""Read-only Alpaca historical daily bars. No trading client is used."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from nomadquant.marketdata.availability import historical_request_end
from nomadquant.marketdata.errors import MarketDataError, SipNotEntitled
from nomadquant.marketdata.validate import (
    ADJUSTMENT,
    CURRENCY,
    PROVIDER,
    TIMEFRAME,
    parse_price,
    parse_volume,
    require_consistent_ohlc,
    require_session_timestamp,
)

DATA_HOST = "https://data.alpaca.markets"
MAX_ATTEMPTS = 4


class FetchedBar:
    def __init__(
        self,
        *,
        symbol: str,
        timestamp: datetime,
        open_: object,
        high: object,
        low: object,
        close: object,
        volume: object,
        feed: str,
    ) -> None:
        session = require_session_timestamp(symbol, timestamp)
        self.symbol = symbol
        self.session_date = session
        self.timestamp = timestamp.astimezone(UTC)
        self.open = parse_price(open_, "open", symbol)
        self.high = parse_price(high, "high", symbol)
        self.low = parse_price(low, "low", symbol)
        self.close = parse_price(close, "close", symbol)
        self.volume = parse_volume(volume, symbol)
        require_consistent_ohlc(symbol, self.open, self.high, self.low, self.close)
        self.provider = PROVIDER
        self.feed = feed
        self.adjustment = ADJUSTMENT
        self.timeframe = TIMEFRAME
        self.currency = CURRENCY


class AlpacaDailyBars:
    """Downloads one feed. SIP and IEX are never merged by this client."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        sleeper: Any = None,
        clock: Any = None,
    ) -> None:
        self._client = StockHistoricalDataClient(
            api_key,
            secret_key,
            url_override=DATA_HOST,
        )
        self._sleep = sleeper if callable(sleeper) else _sleep
        self._clock = clock if callable(clock) else lambda: datetime.now(UTC)

    def fetch(self, symbols: list[str], start: date, end: date, feed: str) -> list[FetchedBar]:
        now = self._clock()
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=datetime(start.year, start.month, start.day, tzinfo=UTC),
            end=historical_request_end(end, now, feed),
            adjustment=Adjustment.RAW,
            feed=_feed(feed),
        )
        payload = self._request(request, feed)
        rows: list[FetchedBar] = []
        for _symbol, bars in payload.data.items():
            for bar in bars:
                rows.append(
                    FetchedBar(
                        symbol=str(bar.symbol),
                        timestamp=_aware(bar.timestamp),
                        open_=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                        feed=feed,
                    )
                )
        return rows

    def _request(self, request: StockBarsRequest, feed: str) -> Any:
        delay = 1.0
        last_kind = "network"
        for attempt in range(MAX_ATTEMPTS):
            try:
                return self._client.get_stock_bars(request)
            except Exception as exc:
                last_kind = _failure_kind(exc, feed)
                if last_kind == "entitlement":
                    raise SipNotEntitled() from None
                if last_kind == "fatal" or attempt == MAX_ATTEMPTS - 1:
                    raise MarketDataError(_safe_message(last_kind)) from None
                self._sleep(delay)
                delay *= 2
        raise MarketDataError(_safe_message(last_kind))


def _feed(feed: str) -> DataFeed:
    if feed == "sip":
        return DataFeed.SIP
    if feed == "iex":
        return DataFeed.IEX
    raise MarketDataError("Feed must be sip or iex.")


def _aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _failure_kind(exc: Exception, feed: str) -> str:
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if feed == "sip" and status in {401, 403}:
        return "entitlement"
    if status == 429:
        return "rate_limited"
    name = type(exc).__name__
    if status in {500, 502, 503, 504} or name in {"ConnectionError", "Timeout", "TimeoutError"}:
        return "network"
    if "Timeout" in name or "Connection" in name:
        return "network"
    return "fatal"


def _safe_message(kind: str) -> str:
    if kind == "rate_limited":
        return "Alpaca market data rate limit. Retry later."
    if kind == "network":
        return "Alpaca market data could not be reached."
    return "Alpaca market data request failed. Details were withheld."


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def year_chunks(start: date, end: date) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        year_end = date(cursor.year, 12, 31)
        chunk_end = min(year_end, end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks
