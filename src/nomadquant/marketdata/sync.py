"""Idempotent daily-bar ingestion. One feed per run."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from nomadquant.marketdata.alpaca_bars import FetchedBar, year_chunks
from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.calendar import is_early_close, is_session
from nomadquant.marketdata.errors import IncompleteSession, InvalidBar, MarketDataError
from nomadquant.marketdata.store import MarketStore, StoredBar, WriteCounts, content_hash

Fetcher = Callable[[list[str], date, date, str], list[FetchedBar]]


@dataclass
class SyncResult:
    feed: str
    start: date
    end: date
    counts: WriteCounts = field(default_factory=WriteCounts)
    warnings: list[str] = field(default_factory=list)
    status: str = "success"
    error_code: str = ""


def sync_daily_bars(
    store: MarketStore,
    fetcher: Fetcher,
    symbols: list[str],
    start: date,
    end: date,
    feed: str,
    now: datetime | None = None,
) -> SyncResult:
    clock = now if now is not None else datetime.now(UTC)
    _require_complete_end(end, clock)
    if feed not in {"sip", "iex"}:
        raise MarketDataError("Feed must be sip or iex.")
    started = clock
    totals = WriteCounts()
    warnings: list[str] = []
    seen: set[str] = set()
    try:
        for chunk_start, chunk_end in year_chunks(start, end):
            fetched = fetcher(symbols, chunk_start, chunk_end, feed)
            _require_single_feed(fetched, feed)
            _reject_duplicate_sessions(fetched)
            _require_chunk_window(fetched, chunk_start, chunk_end)
            seen.update(bar.symbol for bar in fetched)
            stored = [_to_stored(bar, clock) for bar in fetched]
            warnings.extend(_early_close_notes(stored))
            counts = store.write_bars(stored)
            totals = _add(totals, counts)
        for symbol in symbols:
            if symbol not in seen:
                warnings.append(f"{symbol} returned no bars. Missing sessions were not invented.")
    except MarketDataError as exc:
        code = _error_code(exc)
        store.record_run(
            started_at=started,
            symbols=symbols,
            feed=feed,
            start=start,
            end=end,
            status="failed",
            counts=totals,
            warnings=warnings,
            error_code=code,
        )
        raise
    result = SyncResult(feed, start, end, totals, warnings)
    store.record_run(
        started_at=started,
        symbols=symbols,
        feed=feed,
        start=start,
        end=end,
        status="success",
        counts=totals,
        warnings=warnings,
        error_code="",
    )
    return result


def _require_complete_end(end: date, now: datetime) -> None:
    if not is_session(end):
        raise IncompleteSession(f"{end.isoformat()} is not a completed NYSE session.")
    if modeled_available_at(end) > now.astimezone(UTC):
        raise IncompleteSession(
            f"{end.isoformat()} is not available yet. "
            "The close is modeled as knowable at 16:30 America/New_York."
        )


def _reject_duplicate_sessions(bars: list[FetchedBar]) -> None:
    seen: set[tuple[str, date, str]] = set()
    for bar in bars:
        key = (bar.symbol, bar.session_date, bar.feed)
        if key in seen:
            raise InvalidBar(
                f"{bar.symbol} {bar.session_date.isoformat()} appears twice in one download."
            )
        seen.add(key)


def _require_chunk_window(bars: list[FetchedBar], start: date, end: date) -> None:
    outside = [bar for bar in bars if bar.session_date < start or bar.session_date > end]
    if outside:
        sample = outside[0]
        raise InvalidBar(
            f"{sample.symbol} {sample.session_date.isoformat()} is outside the requested window."
        )


def _require_single_feed(bars: list[FetchedBar], feed: str) -> None:
    foreign = sorted({bar.feed for bar in bars if bar.feed != feed})
    if foreign:
        raise MarketDataError(
            f"Refusing to store feed {foreign[0]} in a {feed} import. Feeds are not mixed."
        )


def _to_stored(bar: FetchedBar, retrieved_at: datetime) -> StoredBar:
    stored = StoredBar(
        symbol=bar.symbol,
        session_date=bar.session_date,
        timestamp=bar.timestamp,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        provider=bar.provider,
        feed=bar.feed,
        adjustment=bar.adjustment,
        timeframe=bar.timeframe,
        currency=bar.currency,
        available_at=modeled_available_at(bar.session_date),
        first_retrieved_at=retrieved_at.astimezone(UTC),
        content_hash="",
    )
    return StoredBar(
        symbol=stored.symbol,
        session_date=stored.session_date,
        timestamp=stored.timestamp,
        open=stored.open,
        high=stored.high,
        low=stored.low,
        close=stored.close,
        volume=stored.volume,
        provider=stored.provider,
        feed=stored.feed,
        adjustment=stored.adjustment,
        timeframe=stored.timeframe,
        currency=stored.currency,
        available_at=stored.available_at,
        first_retrieved_at=stored.first_retrieved_at,
        content_hash=content_hash(stored),
    )


def _early_close_notes(bars: list[StoredBar]) -> list[str]:
    notes: list[str] = []
    seen: set[date] = set()
    for bar in bars:
        if bar.session_date in seen or not is_early_close(bar.session_date):
            continue
        seen.add(bar.session_date)
        notes.append(
            f"{bar.session_date.isoformat()} is an early-close session. "
            "Availability is still modeled at 16:30 America/New_York."
        )
    return notes


def _add(left: WriteCounts, right: WriteCounts) -> WriteCounts:
    return WriteCounts(
        left.fetched + right.fetched,
        left.inserted + right.inserted,
        left.unchanged + right.unchanged,
        left.conflicts + right.conflicts,
    )


def _error_code(exc: MarketDataError) -> str:
    name = type(exc).__name__
    if name == "SipNotEntitled":
        return "entitlement"
    if "rate limit" in str(exc):
        return "rate_limited"
    if "could not be reached" in str(exc):
        return "network"
    if name == "InvalidBar":
        return "invalid_bar"
    if name == "IncompleteSession":
        return "incomplete_session"
    return "request_failed"
