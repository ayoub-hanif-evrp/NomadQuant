"""Point-in-time reads over one stored feed."""

from datetime import UTC, datetime

from nomadquant.contracts import Bar
from nomadquant.marketdata.coverage import knowable_sessions
from nomadquant.marketdata.errors import IncompleteCoverage
from nomadquant.marketdata.store import MarketStore


class SqliteMarketDataProvider:
    """Bars for one feed. SIP and IEX observations are never combined."""

    def __init__(self, store: MarketStore, feed: str) -> None:
        if feed not in {"sip", "iex"}:
            raise ValueError("Feed must be sip or iex.")
        self._store = store
        self.feed = feed

    def get_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        as_of: datetime,
    ) -> list[Bar]:
        self._store.require_symbols(symbols, self.feed)
        cutoff = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)
        expected = knowable_sessions(start, end, cutoff)
        for symbol in symbols:
            stored = self._store.sessions(symbol, self.feed)
            missing = [session for session in expected if session not in stored]
            if missing:
                sample = ", ".join(session.isoformat() for session in missing[:5])
                raise IncompleteCoverage(
                    f"{symbol} {self.feed} is missing {len(missing)} knowable sessions, "
                    f"including {sample}. The information cutoff did not withhold them, "
                    "and missing sessions were not invented."
                )
        rows = self._store.bars(symbols, self.feed, start, end, as_of)
        return [
            Bar(
                symbol=row.symbol,
                session_date=row.session_date,
                timestamp=row.timestamp,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                as_of=row.available_at,
                provider=row.provider,
                feed=row.feed,  # type: ignore[arg-type]
                adjustment=row.adjustment,  # type: ignore[arg-type]
                timeframe=row.timeframe,  # type: ignore[arg-type]
                currency=row.currency,
                first_retrieved_at=row.first_retrieved_at,
            )
            for row in rows
        ]
