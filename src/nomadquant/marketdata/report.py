"""Read-only coverage and quality summary. Does not download or invent bars."""

from pathlib import Path

from pydantic import BaseModel, Field

from nomadquant.marketdata.store import MarketStore

CAVEAT = (
    "Raw daily bars are not a dividend-adjusted total-return series. "
    "Modeled availability at 16:30 America/New_York is not a verified "
    "point-in-time archive. first_retrieved_at is when this computer stored the row."
)


class SymbolCoverage(BaseModel):
    symbol: str
    feed: str
    bar_count: int
    earliest_session: str
    latest_session: str
    gap_count: int


class MarketDataStatus(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    feeds: list[str] = Field(default_factory=list)
    earliest_session: str | None = None
    latest_session: str | None = None
    bar_count: int = 0
    coverage: list[SymbolCoverage] = Field(default_factory=list)
    last_successful_ingestion: str | None = None
    warnings: list[str] = Field(default_factory=list)
    suitable_for_research: bool = False
    caveat: str = CAVEAT


def market_data_status(path: str) -> MarketDataStatus:
    if not Path(path).exists():
        return MarketDataStatus(
            warnings=["No local market database yet. Run nomadquant-data sync."]
        )
    store = MarketStore(path)
    coverage_rows = store.coverage()
    coverage: list[SymbolCoverage] = []
    warnings: list[str] = []
    for row in coverage_rows:
        gaps = store.gaps(row["symbol"], row["feed"])
        coverage.append(
            SymbolCoverage(
                symbol=row["symbol"],
                feed=row["feed"],
                bar_count=int(row["bar_count"]),
                earliest_session=row["earliest"],
                latest_session=row["latest"],
                gap_count=len(gaps),
            )
        )
        if gaps:
            sample = ", ".join(day.isoformat() for day in gaps[:5])
            warnings.append(
                f"{row['symbol']} {row['feed']} is missing {len(gaps)} NYSE sessions, "
                f"including {sample}."
            )
    conflicts = store.conflict_count()
    if conflicts:
        warnings.append(
            f"{conflicts} revised bars were kept beside the original rows and were not overwritten."
        )
    success = store.last_success()
    earliest = min((item.earliest_session for item in coverage), default=None)
    latest = max((item.latest_session for item in coverage), default=None)
    feeds = sorted({item.feed for item in coverage})
    symbols = sorted({item.symbol for item in coverage})
    suitable = bool(coverage) and conflicts == 0 and all(item.gap_count == 0 for item in coverage)
    if not coverage:
        warnings.append("The market database has no bars.")
    return MarketDataStatus(
        symbols=symbols,
        feeds=feeds,
        earliest_session=earliest,
        latest_session=latest,
        bar_count=sum(item.bar_count for item in coverage),
        coverage=coverage,
        last_successful_ingestion=None if success is None else success["finished_at"],
        warnings=warnings,
        suitable_for_research=suitable,
    )
