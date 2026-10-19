"""Read-only coverage and quality summary. Does not download or invent bars."""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.coverage import classify_missing
from nomadquant.marketdata.store import MarketStore

CAVEAT = (
    "Raw daily bars are not a dividend-adjusted total-return series. "
    "Modeled availability at 16:30 America/New_York is not a verified "
    "point-in-time archive. first_retrieved_at is when this computer stored the row. "
    "Research readiness is the requested window, not the span of stored rows."
)


class SymbolCoverage(BaseModel):
    symbol: str
    feed: str
    bar_count: int
    earliest_session: str | None = None
    latest_session: str | None = None
    gap_count: int = 0
    missing_start: int = 0
    missing_middle: int = 0
    missing_end: int = 0
    stored_bar_count: int = 0
    stored_earliest_session: str | None = None
    stored_latest_session: str | None = None


class MarketDataStatus(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    feeds: list[str] = Field(default_factory=list)
    earliest_session: str | None = None
    latest_session: str | None = None
    bar_count: int = 0
    requested_start: str | None = None
    requested_end: str | None = None
    requested_feed: str | None = None
    coverage: list[SymbolCoverage] = Field(default_factory=list)
    last_successful_ingestion: str | None = None
    warnings: list[str] = Field(default_factory=list)
    coverage_complete: bool = False
    suitable_for_research: bool = False
    caveat: str = CAVEAT


def market_data_status(
    path: str,
    *,
    start: date | None = None,
    end: date | None = None,
    symbols: list[str] | None = None,
    feed: str | None = None,
) -> MarketDataStatus:
    if not Path(path).exists():
        return MarketDataStatus(
            warnings=["No local market database yet. Run nomadquant-data sync."]
        )
    store = MarketStore.open_readonly(path)
    if store is None:
        return MarketDataStatus(
            warnings=["No local market database yet. Run nomadquant-data sync."]
        )
    success = store.last_success()
    request = _request_window(store, start, end, symbols, feed)
    if request is None:
        return MarketDataStatus(
            warnings=[
                "No requested research window is recorded. "
                "Stored rows alone do not show whether a download was complete."
            ],
            last_successful_ingestion=None if success is None else success["finished_at"],
        )
    window_start, window_end, requested_symbols, requested_feed = request
    expected = sessions_between(window_start, window_end)
    coverage: list[SymbolCoverage] = []
    warnings: list[str] = []
    for symbol in requested_symbols:
        stored = store.sessions(symbol, requested_feed)
        inside = [session for session in expected if session in stored]
        begin, middle, finish = classify_missing(expected, stored)
        missing = len(begin) + len(middle) + len(finish)
        coverage.append(
            SymbolCoverage(
                symbol=symbol,
                feed=requested_feed,
                bar_count=len(inside),
                earliest_session=None if not inside else inside[0].isoformat(),
                latest_session=None if not inside else inside[-1].isoformat(),
                gap_count=missing,
                missing_start=len(begin),
                missing_middle=len(middle),
                missing_end=len(finish),
                stored_bar_count=len(stored),
                stored_earliest_session=None if not stored else min(stored).isoformat(),
                stored_latest_session=None if not stored else max(stored).isoformat(),
            )
        )
        if missing:
            warnings.append(
                f"{symbol} {requested_feed} is missing {missing} sessions in "
                f"{window_start.isoformat()}..{window_end.isoformat()} "
                f"(start {len(begin)}, middle {len(middle)}, end {len(finish)})."
            )
    conflicts = store.conflict_count()
    if conflicts:
        warnings.append(f"{conflicts} distinct revised bars were kept beside the original rows.")
    complete = all(item.gap_count == 0 for item in coverage) and bool(coverage)
    present = [item for item in coverage if item.earliest_session is not None]
    return MarketDataStatus(
        symbols=requested_symbols,
        feeds=[requested_feed],
        earliest_session=min((item.earliest_session or "" for item in present), default=None)
        or None,
        latest_session=max((item.latest_session or "" for item in present), default=None) or None,
        bar_count=sum(item.bar_count for item in coverage),
        requested_start=window_start.isoformat(),
        requested_end=window_end.isoformat(),
        requested_feed=requested_feed,
        coverage=coverage,
        last_successful_ingestion=None if success is None else success["finished_at"],
        warnings=warnings,
        coverage_complete=complete,
        suitable_for_research=complete and conflicts == 0,
    )


def _request_window(
    store: MarketStore,
    start: date | None,
    end: date | None,
    symbols: list[str] | None,
    feed: str | None,
) -> tuple[date, date, list[str], str] | None:
    explicit = [start, end, symbols, feed]
    if any(value is not None for value in explicit):
        if start is None or end is None or symbols is None or feed is None:
            raise ValueError("A coverage check needs --start, --end, --symbols, and --feed.")
        return start, end, symbols, feed
    latest = store.latest_run()
    if latest is None:
        return None
    return (
        date.fromisoformat(latest["start_date"]),
        date.fromisoformat(latest["end_date"]),
        [part for part in str(latest["symbols"]).split(",") if part],
        str(latest["feed"]),
    )
