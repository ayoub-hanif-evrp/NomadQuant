"""Read-only market-data chart routes. No broker orders."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from nomadquant.marketdata.store import MarketStore
from nomadquant.marketdata.validate import ADJUSTMENT, PROVIDER, TIMEFRAME

router = APIRouter(prefix="/api/market-data")

_ALLOWED_SYMBOLS = frozenset({"SPY", "QQQ"})
_ALLOWED_FEEDS = frozenset({"sip", "iex"})

_CAVEAT = (
    "Historical delayed daily bars from the local store. "
    "Not a real-time quote. Feed, adjustment, and provider are explicit."
)


class ChartBar(BaseModel):
    symbol: str
    session_date: str
    bar_timestamp: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    provider: str
    feed: str
    adjustment: str
    timeframe: str
    currency: str
    available_at: str
    first_retrieved_at: str
    content_hash: str


class ChartBarPage(BaseModel):
    items: list[ChartBar]
    total: int
    limit: int
    offset: int
    symbol: str
    feed: str
    provider: str
    adjustment: str
    timeframe: str
    start: str
    end: str
    caveat: str = Field(default=_CAVEAT)


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}. Use YYYY-MM-DD.") from exc


@router.get("/bars", response_model=ChartBarPage)
def market_bars(
    request: Request,
    symbol: str = Query(..., min_length=1, max_length=8),
    feed: str = Query(default="sip"),
    start: str = Query(..., description="Inclusive session start YYYY-MM-DD"),
    end: str = Query(..., description="Inclusive session end YYYY-MM-DD"),
    limit: int = Query(default=2000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> ChartBarPage:
    symbol_key = symbol.strip().upper()
    feed_key = feed.strip().lower()
    if symbol_key not in _ALLOWED_SYMBOLS:
        raise HTTPException(status_code=400, detail="Unsupported symbol. Use SPY or QQQ.")
    if feed_key not in _ALLOWED_FEEDS:
        raise HTTPException(status_code=400, detail="Unsupported feed. Use sip or iex.")
    start_date = _parse_date(start, "start")
    end_date = _parse_date(end, "end")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end must be on or after start.")

    path = request.app.state.settings.market_data_path
    store = MarketStore(path)
    bars, total = store.bars_for_chart(
        symbol_key,
        feed_key,
        start_date,
        end_date,
        provider=PROVIDER,
        adjustment=ADJUSTMENT,
        timeframe=TIMEFRAME,
        limit=limit,
        offset=offset,
    )
    items = [
        ChartBar(
            symbol=bar.symbol,
            session_date=bar.session_date.isoformat(),
            bar_timestamp=bar.timestamp.isoformat(),
            open=str(bar.open),
            high=str(bar.high),
            low=str(bar.low),
            close=str(bar.close),
            volume=str(bar.volume),
            provider=bar.provider,
            feed=bar.feed,
            adjustment=bar.adjustment,
            timeframe=bar.timeframe,
            currency=bar.currency,
            available_at=bar.available_at.isoformat(),
            first_retrieved_at=bar.first_retrieved_at.isoformat(),
            content_hash=bar.content_hash,
        )
        for bar in bars
    ]
    return ChartBarPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        symbol=symbol_key,
        feed=feed_key,
        provider=PROVIDER,
        adjustment=ADJUSTMENT,
        timeframe=TIMEFRAME,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
    )
