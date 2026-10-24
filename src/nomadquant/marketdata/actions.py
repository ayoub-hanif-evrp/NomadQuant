"""Corporate actions and the series derived from them.

Raw bars are never updated. Alpaca's process_date is not an announcement time,
so a download from that API cannot unlock a point-in-time total-return study.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS corporate_actions (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    ratio TEXT,
    cash_per_share TEXT,
    process_date TEXT,
    known_at TEXT,
    retrieved_at TEXT NOT NULL,
    raw_hash TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE TABLE IF NOT EXISTS corporate_action_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    raw_hash TEXT NOT NULL,
    kind TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    ratio TEXT,
    cash_per_share TEXT,
    process_date TEXT,
    known_at TEXT
);
CREATE TABLE IF NOT EXISTS derived_closes (
    symbol TEXT NOT NULL,
    session_date TEXT NOT NULL,
    feed TEXT NOT NULL,
    policy TEXT NOT NULL,
    timing TEXT NOT NULL,
    as_of TEXT NOT NULL,
    close TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (
        symbol, session_date, feed, policy, timing, as_of, source_fingerprint
    )
);
"""

_MODELED = {
    "forward_splits": "forward_split",
    "reverse_splits": "reverse_split",
    "cash_dividends": "cash_dividend",
    "capital_gains_distributions": "capital_gains",
}
_SPLIT = frozenset({"forward_split", "reverse_split"})
_CASH = frozenset({"cash_dividend", "capital_gains"})
ALPACA_LIMIT = (
    "Alpaca does not guarantee when a corporate action was created. "
    "process_date is not an announcement timestamp."
)


@dataclass(frozen=True)
class CorporateAction:
    source: str
    source_id: str
    symbol: str
    kind: str
    ex_date: date
    ratio: Decimal | None
    cash_per_share: Decimal | None
    process_date: date | None
    known_at: datetime | None
    retrieved_at: datetime
    raw_hash: str


@dataclass(frozen=True)
class DerivedSeries:
    prices: dict[str, dict[date, Decimal]]
    usable: bool
    reason: str | None


@dataclass
class ActionDownload:
    actions: list[CorporateAction]
    complete: bool
    reason: str | None
    pages: int


def series_fingerprint(
    prices: dict[str, dict[date, Decimal]],
    *,
    feed: str,
    policy: str,
    timing: str,
    as_of: date,
) -> str:
    rows = [f"{feed}|{policy}|{timing}|{as_of.isoformat()}"]
    for symbol in sorted(prices):
        for day in sorted(prices[symbol]):
            rows.append(f"{symbol}|{day.isoformat()}|{prices[symbol][day]}")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def parse_corporate_actions(
    payload: dict[str, Any],
    *,
    retrieved_at: datetime,
    source: str,
) -> tuple[list[CorporateAction], int]:
    """Parse one Alpaca page. A row missing its documented fields is rejected."""
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware.")
    body = payload.get("corporate_actions")
    if not isinstance(body, dict):
        return [], 1
    actions: list[CorporateAction] = []
    rejected = 0
    for key, rows in body.items():
        if not isinstance(rows, list):
            rejected += 1
            continue
        modeled = _MODELED.get(str(key))
        for row in rows:
            parsed = _row(
                row, kind=modeled or "unmodeled", retrieved_at=retrieved_at, source=source
            )
            if parsed is None:
                rejected += 1
            else:
                actions.append(parsed)
    return actions, rejected


def collect_action_pages(
    fetch_page: Any,
    *,
    retrieved_at: datetime,
    source: str,
    max_pages: int = 20,
) -> ActionDownload:
    """Follow next_page_token. A failed, repeated, or unfinished page is incomplete."""
    seen: set[str] = set()
    token: str | None = None
    collected: list[CorporateAction] = []
    for page_number in range(1, max_pages + 1):
        try:
            payload = fetch_page(token)
        except Exception:
            return ActionDownload(collected, False, "page_failed", page_number)
        if not isinstance(payload, dict):
            return ActionDownload(collected, False, "page_unreadable", page_number)
        parsed, rejected = parse_corporate_actions(
            payload, retrieved_at=retrieved_at, source=source
        )
        if rejected:
            return ActionDownload(collected, False, "rejected_row", page_number)
        collected.extend(parsed)
        nxt = payload.get("next_page_token")
        if not nxt:
            return ActionDownload(collected, True, None, page_number)
        text = str(nxt)
        if text in seen:
            return ActionDownload(collected, False, "repeated_page_token", page_number)
        seen.add(text)
        token = text
    return ActionDownload(collected, False, "page_limit", max_pages)


def derive_closes(
    raw: dict[str, dict[date, Decimal]],
    actions: list[CorporateAction],
    *,
    policy: str,
    timing: str,
    as_of: date,
) -> DerivedSeries:
    """Build one adjustment without writing over the raw closes."""
    if policy not in {"split", "total_return"}:
        return DerivedSeries({}, False, "unsupported_policy")
    if timing not in {"announcement", "as_retrieved"}:
        return DerivedSeries({}, False, "unsupported_timing")
    symbols = set(raw)
    relevant = [item for item in actions if item.symbol in symbols and item.ex_date <= as_of]
    reason = _blocked(relevant, timing)
    if reason is not None:
        return DerivedSeries({}, False, reason)
    derived: dict[str, dict[date, Decimal]] = {}
    for symbol, series in raw.items():
        days = sorted(day for day in series if day <= as_of and series[day] > 0)
        if not days:
            derived[symbol] = {}
            continue
        split_px = {
            day: series[day] / _split_product(actions, symbol, day, as_of, timing) for day in days
        }
        if policy == "split":
            derived[symbol] = split_px
            continue
        total: dict[date, Decimal] = {days[0]: split_px[days[0]]}
        for previous, day in zip(days, days[1:], strict=False):
            cash = _cash_on(actions, symbol, day, as_of, timing)
            total[day] = total[previous] * (split_px[day] + cash) / split_px[previous]
        derived[symbol] = total
    return DerivedSeries(derived, True, None)


def describe_actions(
    actions: list[CorporateAction],
    raw: dict[str, dict[date, Decimal]],
    *,
    policy: str,
    timing: str,
    as_of: date,
    feed: str,
    checked: bool,
) -> dict[str, Any]:
    """Say what this action set is allowed to prove. It does not download anything."""
    derived = derive_closes(raw, actions, policy=policy, timing=timing, as_of=as_of)
    fingerprint = None
    if derived.usable:
        fingerprint = series_fingerprint(
            derived.prices, feed=feed, policy=policy, timing=timing, as_of=as_of
        )
    pit = (
        checked
        and derived.usable
        and policy == "total_return"
        and timing == "announcement"
        and feed in {"iex", "sip"}
    )
    if pit:
        reason = None
        research_state = "EVALUABLE"
    elif derived.reason is not None:
        reason = derived.reason
        research_state = "NOT_EVALUABLE"
    elif timing != "announcement":
        reason = "alpaca_process_date_is_not_an_announcement_time"
        research_state = "NOT_EVALUABLE"
    elif policy != "total_return":
        reason = "total_return_dataset_absent"
        research_state = "NOT_EVALUABLE"
    elif not checked:
        reason = "announcement_check_not_recorded"
        research_state = "NOT_EVALUABLE"
    else:
        reason = "feed_not_distinct"
        research_state = "NOT_EVALUABLE"
    return {
        "provider": "alpaca",
        "adjustment": policy if derived.usable else "raw",
        "timing": timing,
        "as_of": as_of.isoformat(),
        "feed": feed,
        "feeds": ["iex", "sip"],
        "feeds_are_distinct": True,
        "corporate_actions": "stored" if actions else "none_in_snapshot",
        "split_adjusted_dataset": derived.usable and policy in {"split", "total_return"},
        "dividend_adjusted_dataset": derived.usable and policy == "total_return",
        "point_in_time_total_return": pit,
        "series_fingerprint": fingerprint,
        "action_count": len(actions),
        "cash_distribution_count": sum(1 for item in actions if item.kind in _CASH),
        "unmodeled_count": sum(1 for item in actions if item.kind == "unmodeled"),
        "research_state": research_state,
        "reason": reason,
        "permission_to_trade": False,
        "caveat": ALPACA_LIMIT,
        "derived_prices": derived.prices,
    }


class ActionStore:
    """Append-only action log. Opening it does not change stored bars."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def write(self, actions: list[CorporateAction]) -> tuple[int, int, int]:
        inserted = unchanged = revisions = 0
        with self._connect() as connection:
            for action in actions:
                _require_aware(action.retrieved_at, "retrieved_at")
                if action.known_at is not None:
                    _require_aware(action.known_at, "known_at")
                row = connection.execute(
                    "SELECT raw_hash FROM corporate_actions WHERE source = ? AND source_id = ?",
                    (action.source, action.source_id),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO corporate_actions (
                            source, source_id, symbol, kind, ex_date, ratio, cash_per_share,
                            process_date, known_at, retrieved_at, raw_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        _fields(action),
                    )
                    inserted += 1
                elif row["raw_hash"] == action.raw_hash:
                    unchanged += 1
                else:
                    connection.execute(
                        """
                        INSERT INTO corporate_action_revisions (
                            source, source_id, observed_at, raw_hash, kind, ex_date, ratio,
                            cash_per_share, process_date, known_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            action.source,
                            action.source_id,
                            _iso(action.retrieved_at),
                            action.raw_hash,
                            action.kind,
                            action.ex_date.isoformat(),
                            _text(action.ratio),
                            _text(action.cash_per_share),
                            _day(action.process_date),
                            None if action.known_at is None else _iso(action.known_at),
                        ),
                    )
                    revisions += 1
        return inserted, unchanged, revisions

    def load(self) -> list[CorporateAction]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM corporate_actions ORDER BY ex_date, symbol, source_id"
            ).fetchall()
        return [_loaded(row) for row in rows]

    def revision_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM corporate_action_revisions"
            ).fetchone()
        return int(row["n"])

    def write_derived(
        self,
        prices: dict[str, dict[date, Decimal]],
        *,
        feed: str,
        policy: str,
        timing: str,
        as_of: date,
        fingerprint: str,
        computed_at: datetime,
    ) -> int:
        if policy == "raw":
            raise ValueError("A derived dataset cannot overwrite the raw policy.")
        _require_aware(computed_at, "computed_at")
        written = 0
        with self._connect() as connection:
            for symbol, series in prices.items():
                for day, close in series.items():
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO derived_closes (
                            symbol, session_date, feed, policy, timing, as_of, close,
                            source_fingerprint, computed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            symbol,
                            day.isoformat(),
                            feed,
                            policy,
                            timing,
                            as_of.isoformat(),
                            str(close),
                            fingerprint,
                            _iso(computed_at),
                        ),
                    )
                    written += 1
        return written

    def derived_close(
        self,
        symbol: str,
        session: date,
        *,
        feed: str,
        policy: str,
        timing: str,
        as_of: date,
    ) -> Decimal | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT close FROM derived_closes
                WHERE symbol = ? AND session_date = ? AND feed = ? AND policy = ?
                  AND timing = ? AND as_of = ?
                """,
                (symbol, session.isoformat(), feed, policy, timing, as_of.isoformat()),
            ).fetchone()
        return None if row is None else Decimal(row["close"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def _blocked(actions: list[CorporateAction], timing: str) -> str | None:
    for action in actions:
        if action.kind == "unmodeled":
            return "unmodeled_corporate_action"
        if timing == "announcement" and action.known_at is None:
            return "action_missing_announcement_time"
        if timing == "as_retrieved" and action.process_date is None:
            return "action_missing_process_date"
    return None


def _known(action: CorporateAction, as_of: date, timing: str) -> bool:
    if action.ex_date > as_of:
        return False
    if timing == "announcement":
        return action.known_at is not None and action.known_at.astimezone(UTC).date() <= as_of
    return action.process_date is not None and action.process_date <= as_of


def _split_product(
    actions: list[CorporateAction],
    symbol: str,
    session: date,
    as_of: date,
    timing: str,
) -> Decimal:
    product = Decimal("1")
    for action in actions:
        if action.symbol != symbol or action.kind not in _SPLIT or action.ratio is None:
            continue
        if session < action.ex_date <= as_of and _known(action, as_of, timing):
            product *= action.ratio
    return product


def _cash_on(
    actions: list[CorporateAction],
    symbol: str,
    session: date,
    as_of: date,
    timing: str,
) -> Decimal:
    total = Decimal("0")
    later = _split_product(actions, symbol, session, as_of, timing)
    for action in actions:
        if (
            action.symbol == symbol
            and action.kind in _CASH
            and action.ex_date == session
            and action.cash_per_share is not None
            and _known(action, as_of, timing)
        ):
            total += action.cash_per_share / later
    return total


def _row(
    row: Any,
    *,
    kind: str,
    retrieved_at: datetime,
    source: str,
) -> CorporateAction | None:
    if not isinstance(row, dict):
        return None
    source_id = str(row.get("id") or "")
    symbol = str(row.get("symbol") or row.get("old_symbol") or row.get("acquiree_symbol") or "")
    ex_text = row.get("ex_date") or row.get("effective_date") or row.get("process_date")
    if not source_id or not symbol or not isinstance(ex_text, str):
        return None
    try:
        ex_date = date.fromisoformat(ex_text)
    except ValueError:
        return None
    process = _optional_date(row.get("process_date"))
    ratio: Decimal | None = None
    cash: Decimal | None = None
    if kind in _SPLIT:
        new_rate = _positive(row.get("new_rate"))
        old_rate = _positive(row.get("old_rate"))
        if new_rate is None or old_rate is None:
            return None
        ratio = new_rate / old_rate
    elif kind in _CASH:
        if kind == "capital_gains":
            long_rate = _optional_positive(row.get("long_term_rate"))
            short_rate = _optional_positive(row.get("short_term_rate"))
            if long_rate is None and short_rate is None:
                return None
            cash = (long_rate or Decimal("0")) + (short_rate or Decimal("0"))
        else:
            cash = _positive(row.get("rate"))
            if cash is None:
                return None
    digest = hashlib.sha256(
        "|".join(
            [
                source,
                source_id,
                symbol.upper(),
                kind,
                ex_date.isoformat(),
                "" if ratio is None else format(ratio, "f"),
                "" if cash is None else format(cash, "f"),
                "" if process is None else process.isoformat(),
            ]
        ).encode("utf-8")
    ).hexdigest()
    return CorporateAction(
        source=source,
        source_id=source_id,
        symbol=symbol.upper(),
        kind=kind,
        ex_date=ex_date,
        ratio=ratio,
        cash_per_share=cash,
        process_date=process,
        known_at=None,
        retrieved_at=retrieved_at.astimezone(UTC),
        raw_hash=digest,
    )


def _positive(value: object) -> Decimal | None:
    number = _optional_positive(value)
    return None if number is None or number <= 0 else number


def _optional_positive(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    if not number.is_finite() or number < 0:
        return None
    return number


def _optional_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _fields(action: CorporateAction) -> tuple[object, ...]:
    return (
        action.source,
        action.source_id,
        action.symbol,
        action.kind,
        action.ex_date.isoformat(),
        _text(action.ratio),
        _text(action.cash_per_share),
        _day(action.process_date),
        None if action.known_at is None else _iso(action.known_at),
        _iso(action.retrieved_at),
        action.raw_hash,
    )


def _loaded(row: sqlite3.Row) -> CorporateAction:
    return CorporateAction(
        source=row["source"],
        source_id=row["source_id"],
        symbol=row["symbol"],
        kind=row["kind"],
        ex_date=date.fromisoformat(row["ex_date"]),
        ratio=None if row["ratio"] is None else Decimal(row["ratio"]),
        cash_per_share=None if row["cash_per_share"] is None else Decimal(row["cash_per_share"]),
        process_date=None
        if row["process_date"] is None
        else date.fromisoformat(row["process_date"]),
        known_at=None if row["known_at"] is None else datetime.fromisoformat(row["known_at"]),
        retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
        raw_hash=row["raw_hash"],
    )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()
