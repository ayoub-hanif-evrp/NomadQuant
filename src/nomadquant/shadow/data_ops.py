"""Read-only market-data readiness for the shadow worker. No order paths."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore
from nomadquant.shadow.cycle import FEED, LOOKBACK, SKIP, SYMBOL


def data_check(
    settings: Settings, *, feed: str = FEED, as_of: datetime | None = None
) -> dict[str, Any]:
    """Report missing completed sessions for the configured feed. No download."""
    now = as_of or datetime.now(UTC)
    path = Path(settings.market_data_path)
    if feed not in {"sip", "iex"}:
        return {"status": "ERROR", "reason": f"unsupported feed {feed}"}
    if not path.exists():
        return {
            "status": "WAITING_FOR_DATA",
            "feed": feed,
            "reason": "market database missing",
            "missing_sessions": [],
        }
    market = MarketStore(path)
    if not market.has_symbol(SYMBOL, feed):
        return {
            "status": "WAITING_FOR_DATA",
            "feed": feed,
            "symbol": SYMBOL,
            "reason": f"no {SYMBOL}/{feed} bars",
            "missing_sessions": [],
        }
    stored = sorted(market.sessions(SYMBOL, feed))
    today = now.astimezone(UTC).date() if now.tzinfo else date.today()
    cal = sessions_between(stored[0], today) if stored else []
    eligible = [s for s in cal if modeled_available_at(s) <= now]
    eligible_end = eligible[-1] if eligible else stored[-1]
    expected = sessions_between(stored[0], eligible_end) if stored else []
    stored_set = set(stored)
    missing = [s.isoformat() for s in expected if s not in stored_set]
    warmup_ok = len(stored) >= LOOKBACK + SKIP + 5
    return {
        "status": "OK" if not missing and warmup_ok else "WAITING_FOR_DATA",
        "feed": feed,
        "symbol": SYMBOL,
        "stored_sessions": len(stored),
        "earliest": None if not stored else stored[0].isoformat(),
        "latest_stored": None if not stored else stored[-1].isoformat(),
        "eligible_end": eligible_end.isoformat(),
        "missing_count": len(missing),
        "missing_sessions": missing[-20:],
        "warmup_ok": warmup_ok,
        "note": (
            "Check only. Sync is opt-in and read-only. "
            "Never mixes SIP and IEX. Incomplete current session is excluded."
        ),
    }
