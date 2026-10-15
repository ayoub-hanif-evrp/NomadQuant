"""SQLite store for daily research bars. Separate from operational events."""

import hashlib
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.errors import MissingMarketData
from nomadquant.marketdata.validate import ADJUSTMENT, PROVIDER, TIMEFRAME

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    session_date TEXT NOT NULL,
    bar_timestamp TEXT NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    volume TEXT NOT NULL,
    provider TEXT NOT NULL,
    feed TEXT NOT NULL,
    adjustment TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    currency TEXT NOT NULL,
    available_at TEXT NOT NULL,
    first_retrieved_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (symbol, session_date, feed, timeframe, adjustment, provider)
);
CREATE TABLE IF NOT EXISTS bar_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    session_date TEXT NOT NULL,
    feed TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    adjustment TEXT NOT NULL,
    provider TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    volume TEXT NOT NULL,
    bar_timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    symbols TEXT NOT NULL,
    feed TEXT NOT NULL,
    adjustment TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL,
    rows_fetched INTEGER NOT NULL,
    rows_inserted INTEGER NOT NULL,
    rows_unchanged INTEGER NOT NULL,
    rows_conflict INTEGER NOT NULL,
    warnings TEXT NOT NULL,
    error_code TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class StoredBar:
    symbol: str
    session_date: date
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    provider: str
    feed: str
    adjustment: str
    timeframe: str
    currency: str
    available_at: datetime
    first_retrieved_at: datetime
    content_hash: str


@dataclass(frozen=True)
class WriteCounts:
    fetched: int = 0
    inserted: int = 0
    unchanged: int = 0
    conflicts: int = 0


def content_hash(bar: StoredBar) -> str:
    payload = "|".join(
        [
            bar.symbol,
            bar.session_date.isoformat(),
            bar.timestamp.isoformat(),
            str(bar.open),
            str(bar.high),
            str(bar.low),
            str(bar.close),
            str(bar.volume),
            bar.provider,
            bar.feed,
            bar.adjustment,
            bar.timeframe,
            bar.currency,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MarketStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            _migrate(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def write_bars(self, bars: list[StoredBar]) -> WriteCounts:
        inserted = unchanged = conflicts = 0
        with self._connect() as connection:
            for bar in bars:
                stored = _with_hash(bar, content_hash(bar))
                row = connection.execute(
                    """
                    SELECT content_hash FROM bars
                    WHERE symbol = ? AND session_date = ? AND feed = ?
                      AND timeframe = ? AND adjustment = ? AND provider = ?
                    """,
                    _key(stored),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO bars (
                            symbol, session_date, bar_timestamp, open, high, low, close,
                            volume, provider, feed, adjustment, timeframe, currency,
                            available_at, first_retrieved_at, content_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        _row(stored),
                    )
                    inserted += 1
                elif row["content_hash"] == stored.content_hash:
                    unchanged += 1
                elif _revision_exists(connection, stored):
                    unchanged += 1
                else:
                    connection.execute(
                        """
                        INSERT INTO bar_revisions (
                            symbol, session_date, feed, timeframe, adjustment, provider,
                            observed_at, content_hash, open, high, low, close, volume,
                            bar_timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            stored.symbol,
                            stored.session_date.isoformat(),
                            stored.feed,
                            stored.timeframe,
                            stored.adjustment,
                            stored.provider,
                            _iso(stored.first_retrieved_at),
                            stored.content_hash,
                            str(stored.open),
                            str(stored.high),
                            str(stored.low),
                            str(stored.close),
                            str(stored.volume),
                            _iso(stored.timestamp),
                        ),
                    )
                    conflicts += 1
        return WriteCounts(len(bars), inserted, unchanged, conflicts)

    def record_run(
        self,
        *,
        started_at: datetime,
        symbols: list[str],
        feed: str,
        start: date,
        end: date,
        status: str,
        counts: WriteCounts,
        warnings: list[str],
        error_code: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO import_runs (
                    started_at, finished_at, symbols, feed, adjustment, timeframe,
                    start_date, end_date, status, rows_fetched, rows_inserted,
                    rows_unchanged, rows_conflict, warnings, error_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _iso(started_at),
                    _iso(datetime.now(UTC)),
                    ",".join(symbols),
                    feed,
                    ADJUSTMENT,
                    TIMEFRAME,
                    start.isoformat(),
                    end.isoformat(),
                    status,
                    counts.fetched,
                    counts.inserted,
                    counts.unchanged,
                    counts.conflicts,
                    "\n".join(warnings),
                    error_code,
                ),
            )

    def bars(
        self,
        symbols: list[str],
        feed: str,
        start: datetime,
        end: datetime,
        available_by: datetime,
    ) -> list[StoredBar]:
        if not symbols:
            return []
        placeholders = ",".join("?" for _ in symbols)
        query = f"""
            SELECT * FROM bars
            WHERE symbol IN ({placeholders})
              AND feed = ?
              AND provider = ?
              AND adjustment = ?
              AND timeframe = ?
              AND bar_timestamp >= ?
              AND bar_timestamp <= ?
              AND available_at <= ?
            ORDER BY session_date, symbol
        """
        params: list[object] = [
            *symbols,
            feed,
            PROVIDER,
            ADJUSTMENT,
            TIMEFRAME,
            _iso(start),
            _iso(end),
            _iso(available_by),
        ]
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_stored(row) for row in rows]

    def has_symbol(self, symbol: str, feed: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM bars WHERE symbol = ? AND feed = ? LIMIT 1",
                (symbol, feed),
            ).fetchone()
        return row is not None

    def require_symbols(self, symbols: list[str], feed: str) -> None:
        missing = [symbol for symbol in symbols if not self.has_symbol(symbol, feed)]
        if missing:
            joined = ", ".join(missing)
            raise MissingMarketData(
                f"No stored {feed} bars for {joined}. Missing sessions are not filled in."
            )

    def coverage(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT symbol, feed, COUNT(*) AS bar_count,
                       MIN(session_date) AS earliest, MAX(session_date) AS latest
                FROM bars
                GROUP BY symbol, feed
                ORDER BY symbol, feed
                """
            ).fetchall()

    def conflict_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM bar_revisions").fetchone()
        return int(row["n"]) if row is not None else 0

    def sessions(self, symbol: str, feed: str) -> set[date]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT session_date FROM bars WHERE symbol = ? AND feed = ?",
                (symbol, feed),
            ).fetchall()
        return {date.fromisoformat(row["session_date"]) for row in rows}

    def bar_hashes(self, symbol: str, feed: str, start: date, end: date) -> list[tuple[date, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_date, content_hash FROM bars
                WHERE symbol = ? AND feed = ? AND session_date >= ? AND session_date <= ?
                ORDER BY session_date
                """,
                (symbol, feed, start.isoformat(), end.isoformat()),
            ).fetchall()
        return [(date.fromisoformat(row["session_date"]), str(row["content_hash"])) for row in rows]

    def session_ohlc(
        self, symbol: str, feed: str, start: date, end: date
    ) -> list[tuple[date, Decimal, Decimal, Decimal, Decimal]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_date, open, high, low, close FROM bars
                WHERE symbol = ? AND feed = ? AND session_date >= ? AND session_date <= ?
                ORDER BY session_date
                """,
                (symbol, feed, start.isoformat(), end.isoformat()),
            ).fetchall()
        return [
            (
                date.fromisoformat(row["session_date"]),
                Decimal(row["open"]),
                Decimal(row["high"]),
                Decimal(row["low"]),
                Decimal(row["close"]),
            )
            for row in rows
        ]

    def bars_for_chart(
        self,
        symbol: str,
        feed: str,
        start: date,
        end: date,
        *,
        provider: str = PROVIDER,
        adjustment: str = ADJUSTMENT,
        timeframe: str = TIMEFRAME,
        limit: int = 2000,
        offset: int = 0,
    ) -> tuple[list[StoredBar], int]:
        """Read stored OHLCV for charts by session_date (not point-in-time)."""
        bounded_limit = min(max(limit, 1), 5000)
        bounded_offset = max(offset, 0)
        where = """
            symbol = ? AND feed = ? AND provider = ? AND adjustment = ? AND timeframe = ?
            AND session_date >= ? AND session_date <= ?
        """
        params: list[object] = [
            symbol,
            feed,
            provider,
            adjustment,
            timeframe,
            start.isoformat(),
            end.isoformat(),
        ]
        with self._connect() as connection:
            total = int(
                connection.execute(f"SELECT COUNT(*) FROM bars WHERE {where}", params).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT * FROM bars
                WHERE {where}
                ORDER BY session_date ASC
                LIMIT ? OFFSET ?
                """,
                [*params, bounded_limit, bounded_offset],
            ).fetchall()
        return [_stored(row) for row in rows], total

    def revision_count(self, symbol: str, feed: str, start: date, end: date) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS n FROM bar_revisions
                WHERE symbol = ? AND feed = ? AND session_date >= ? AND session_date <= ?
                """,
                (symbol, feed, start.isoformat(), end.isoformat()),
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    def latest_run(self) -> sqlite3.Row | None:
        with self._connect() as connection:
            rows: Sequence[sqlite3.Row] = connection.execute(
                "SELECT * FROM import_runs ORDER BY id DESC LIMIT 1"
            ).fetchall()
        return rows[0] if rows else None

    def last_success(self) -> sqlite3.Row | None:
        with self._connect() as connection:
            rows: Sequence[sqlite3.Row] = connection.execute(
                """
                SELECT * FROM import_runs
                WHERE status = 'success'
                ORDER BY finished_at DESC
                LIMIT 1
                """
            ).fetchall()
        return rows[0] if rows else None

    def gaps(self, symbol: str, feed: str) -> list[date]:
        with self._connect() as connection:
            bounds = connection.execute(
                """
                SELECT MIN(session_date) AS earliest, MAX(session_date) AS latest
                FROM bars WHERE symbol = ? AND feed = ?
                """,
                (symbol, feed),
            ).fetchone()
            if bounds is None or bounds["earliest"] is None:
                return []
            stored = {
                date.fromisoformat(row["session_date"])
                for row in connection.execute(
                    "SELECT session_date FROM bars WHERE symbol = ? AND feed = ?",
                    (symbol, feed),
                )
            }
        expected = sessions_between(
            date.fromisoformat(bounds["earliest"]),
            date.fromisoformat(bounds["latest"]),
        )
        return [session for session in expected if session not in stored]


def _with_hash(bar: StoredBar, digest: str) -> StoredBar:
    return StoredBar(
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
        available_at=bar.available_at,
        first_retrieved_at=bar.first_retrieved_at,
        content_hash=digest,
    )


def _key(bar: StoredBar) -> tuple[str, str, str, str, str, str]:
    return (
        bar.symbol,
        bar.session_date.isoformat(),
        bar.feed,
        bar.timeframe,
        bar.adjustment,
        bar.provider,
    )


def _row(bar: StoredBar) -> tuple[object, ...]:
    return (
        bar.symbol,
        bar.session_date.isoformat(),
        _iso(bar.timestamp),
        str(bar.open),
        str(bar.high),
        str(bar.low),
        str(bar.close),
        str(bar.volume),
        bar.provider,
        bar.feed,
        bar.adjustment,
        bar.timeframe,
        bar.currency,
        _iso(bar.available_at),
        _iso(bar.first_retrieved_at),
        bar.content_hash,
    )


def _stored(row: sqlite3.Row) -> StoredBar:
    return StoredBar(
        symbol=row["symbol"],
        session_date=date.fromisoformat(row["session_date"]),
        timestamp=datetime.fromisoformat(row["bar_timestamp"]),
        open=Decimal(row["open"]),
        high=Decimal(row["high"]),
        low=Decimal(row["low"]),
        close=Decimal(row["close"]),
        volume=Decimal(row["volume"]),
        provider=row["provider"],
        feed=row["feed"],
        adjustment=row["adjustment"],
        timeframe=row["timeframe"],
        currency=row["currency"],
        available_at=datetime.fromisoformat(row["available_at"]),
        first_retrieved_at=datetime.fromisoformat(row["first_retrieved_at"]),
        content_hash=row["content_hash"],
    )


def _revision_exists(connection: sqlite3.Connection, bar: StoredBar) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM bar_revisions
        WHERE symbol = ? AND session_date = ? AND feed = ?
          AND timeframe = ? AND adjustment = ? AND provider = ?
          AND content_hash = ?
        """,
        (*_key(bar), bar.content_hash),
    ).fetchone()
    return row is not None


def _migrate(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        DELETE FROM bar_revisions
        WHERE id NOT IN (
            SELECT MIN(id) FROM bar_revisions
            GROUP BY symbol, session_date, feed, timeframe, adjustment, provider, content_hash
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS bar_revisions_identity
        ON bar_revisions (
            symbol, session_date, feed, timeframe, adjustment, provider, content_hash
        )
        """
    )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
