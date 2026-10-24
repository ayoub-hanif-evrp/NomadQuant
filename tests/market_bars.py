"""Write the closes a paper-submission test claims were already available."""

from datetime import UTC, date, datetime
from decimal import Decimal

from nomadquant.config import Settings
from nomadquant.marketdata.store import MarketStore, StoredBar, content_hash
from nomadquant.marketdata.validate import ADJUSTMENT, PROVIDER, TIMEFRAME


def seed_closes(
    settings: Settings,
    prices: dict[str, dict[date, Decimal]],
    *,
    now: datetime,
    feed: str = "iex",
) -> None:
    store = MarketStore(settings.market_data_path)
    bars: list[StoredBar] = []
    stamp = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    for symbol, series in prices.items():
        for day, close in series.items():
            bar = StoredBar(
                symbol=symbol,
                session_date=day,
                timestamp=stamp,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("1"),
                provider=PROVIDER,
                feed=feed,
                adjustment=ADJUSTMENT,
                timeframe=TIMEFRAME,
                currency="USD",
                available_at=stamp,
                first_retrieved_at=stamp,
                content_hash="",
            )
            bars.append(StoredBar(**{**bar.__dict__, "content_hash": content_hash(bar)}))
    store.write_bars(bars)
