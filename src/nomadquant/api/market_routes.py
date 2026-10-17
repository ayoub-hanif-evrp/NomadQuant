"""Market-data routes. Chart reads are GET. Sync is an explicit localhost POST."""

from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from nomadquant.api.csrf import require_local_mutation
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


@router.get("/freshness")
def market_freshness(request: Request) -> dict[str, Any]:
    """Compare the stored daily bar with the latest eligible session. Does not download."""
    from nomadquant.marketdata.availability import latest_safe_session
    from nomadquant.shadow.data_ops import data_check

    now = datetime.now(UTC)
    settings = request.app.state.settings
    try:
        eligible = latest_safe_session(now, "sip").isoformat()
    except Exception:  # noqa: BLE001 - the page must still explain the gap
        eligible = None
    report = data_check(settings, feed="sip")
    return {
        "as_of": now.isoformat(),
        "feed": "sip",
        "timeframe": "1Day",
        "live": False,
        "entitlement": "historical_daily_bars",
        "eligible_session": eligible,
        "symbols": report.get("symbols") or {},
        "missing_count": report.get("missing_count"),
        "status": report.get("status"),
        "note": "Daily bars are delayed historical records. A page refresh is not a live quote.",
        "broker_orders": False,
    }


@router.get("/live-quote")
def market_live_quote(request: Request) -> dict[str, Any]:
    """Display-only IEX snapshot, cached for 15 seconds. Not a strategy input."""
    from nomadquant.marketdata.live_quote import live_quotes

    return live_quotes(request.app.state.settings)


class SyncBody(BaseModel):
    confirm: str


@router.post("/sync")
def sync_historical_bars(body: SyncBody, request: Request) -> dict[str, Any]:
    """Opt-in download of missing daily bars. Does not change the strategy feed."""
    require_local_mutation(request)
    if body.confirm != "SYNC_HISTORICAL_BARS":
        raise HTTPException(status_code=409, detail="Confirmation phrase does not match.")
    from nomadquant.shadow.data_ops import data_sync

    result = data_sync(request.app.state.settings, feed="sip")
    result["broker_orders"] = False
    return result
