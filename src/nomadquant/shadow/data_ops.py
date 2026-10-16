"""Market-data check and opt-in incremental sync. Read-only toward the broker."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.marketdata.availability import latest_safe_session, modeled_available_at
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.errors import MarketDataError, SipNotEntitled
from nomadquant.marketdata.store import MarketStore
from nomadquant.marketdata.sync import Fetcher, sync_daily_bars
from nomadquant.shadow.cycle import FEED, LOOKBACK, SKIP

SYMBOLS = ("SPY", "QQQ")
_WARMUP = LOOKBACK + SKIP + 5


def data_check(
    settings: Settings, *, feed: str = FEED, as_of: datetime | None = None
) -> dict[str, Any]:
    """Report missing sessions inside the strategy warm-up window. No download."""
    now = as_of or datetime.now(UTC)
    if feed not in {"sip", "iex"}:
        return {"status": "ERROR", "reason": f"unsupported feed {feed}"}
    path = Path(settings.market_data_path)
    end = latest_safe_session(now, feed)
    window = _required_window(end)
    if not path.exists():
        return {
            "status": "WAITING_FOR_DATA",
            "feed": feed,
            "symbols": {},
            "reason": "market database missing",
            "eligible_end": end.isoformat(),
            "required_start": window[0].isoformat() if window else None,
            "missing_sessions": [s.isoformat() for s in window[:30]],
            "missing_count": len(window) * len(SYMBOLS),
        }
    market = MarketStore.open_readonly(path)
    if market is None:
        return {
            "status": "WAITING_FOR_DATA",
            "feed": feed,
            "symbols": {},
            "reason": "market database missing",
            "missing_sessions": [],
        }
    per_symbol: dict[str, Any] = {}
    any_missing = False
    for symbol in SYMBOLS:
        stored = market.sessions(symbol, feed) if market.has_symbol(symbol, feed) else set()
        missing = [s for s in window if s not in stored]
        any_missing = any_missing or bool(missing)
        per_symbol[symbol] = {
            "stored_sessions": len(stored),
            "latest_stored": None if not stored else max(stored).isoformat(),
            "missing_count": len(missing),
            "missing_sessions": [s.isoformat() for s in missing[:30]],
            "warmup_complete": len(missing) == 0 and len(stored) >= _WARMUP,
        }
    return {
        "status": "OK" if not any_missing else "WAITING_FOR_DATA",
        "feed": feed,
        "symbol": "SPY",
        "symbols": per_symbol,
        "eligible_end": end.isoformat(),
        "required_start": window[0].isoformat() if window else None,
        "required_end": window[-1].isoformat() if window else None,
        "missing_count": sum(int(v["missing_count"]) for v in per_symbol.values()),
        "missing_sessions": per_symbol.get("SPY", {}).get("missing_sessions", []),
        "warmup_ok": all(v["warmup_complete"] for v in per_symbol.values()),
        "note": (
            "Check only. Sync is opt-in. Never mixes SIP and IEX. "
            "Window is the strategy warm-up through the latest safe completed session."
        ),
    }


def plan_missing_requests(
    window: list[date], stored_by_symbol: dict[str, set[date]]
) -> list[tuple[tuple[str, ...], date, date]]:
    """Group adjacent missing sessions. Symbols that are already complete are omitted."""
    buckets: dict[tuple[date, date], list[str]] = {}
    for symbol, stored in stored_by_symbol.items():
        for start, end in _missing_intervals(window, stored):
            buckets.setdefault((start, end), []).append(symbol)
    return [
        (tuple(buckets[key]), key[0], key[1])
        for key in sorted(buckets, key=lambda item: (item[0], item[1]))
    ]


def data_sync(
    settings: Settings,
    *,
    feed: str = FEED,
    fetcher: Fetcher | None = None,
    as_of: datetime | None = None,
    revision_audit: bool = False,
) -> dict[str, Any]:
    """Download missing sessions, or re-check stored bars when revision_audit is set."""
    now = as_of or datetime.now(UTC)
    report = data_check(settings, feed=feed, as_of=now)
    if report.get("status") == "ERROR":
        return report
    end = latest_safe_session(now, feed)
    window = _required_window(end)
    if not window:
        return {**report, "sync": "noop", "inserted": 0, "reason": "empty_required_window"}
    if (
        not revision_audit
        and report.get("missing_count", 0) == 0
        and Path(settings.market_data_path).exists()
    ):
        return {
            **report,
            "sync": "noop",
            "inserted": 0,
            "provider_requests": 0,
            "rows_fetched": 0,
        }
    if fetcher is None:
        try:
            fetcher = _live_fetcher(settings)
        except RuntimeError as exc:
            return {
                **report,
                "status": "ERROR",
                "sync": "failed",
                "error_code": "missing_credentials",
                "feed_used": feed,
                "remediation": str(exc),
            }
    store = MarketStore(settings.market_data_path)
    stored = {
        symbol: store.sessions(symbol, feed) if store.has_symbol(symbol, feed) else set()
        for symbol in SYMBOLS
    }
    requests = (
        [(SYMBOLS, window[0], end)] if revision_audit else plan_missing_requests(window, stored)
    )
    if not requests:
        return {**report, "sync": "noop", "inserted": 0, "provider_requests": 0, "rows_fetched": 0}
    calls: list[tuple[Any, ...]] = []

    def _counting(symbols: list[str], start: date, end_day: date, requested_feed: str) -> Any:
        calls.append((tuple(symbols), start, end_day, requested_feed))
        return fetcher(symbols, start, end_day, requested_feed)

    inserted = unchanged = conflicts = fetched = 0
    warnings: list[str] = []
    status = "success"
    try:
        for symbols, start, stop in requests:
            result = sync_daily_bars(store, _counting, list(symbols), start, stop, feed, now=now)
            inserted += result.counts.inserted
            unchanged += result.counts.unchanged
            conflicts += result.counts.conflicts
            fetched += result.counts.fetched
            warnings.extend(result.warnings)
            if result.status != "success":
                status = result.status
    except SipNotEntitled:
        return {
            **report,
            "status": "ERROR",
            "sync": "failed",
            "error_code": "entitlement",
            "feed_used": feed,
            "remediation": (
                "This account cannot read SIP history. The shadow hypothesis stays on SIP. "
                "Do not switch the strategy feed automatically. "
                "Obtain SIP entitlement, or run an explicit separate dataset with --feed iex."
            ),
        }
    except MarketDataError as exc:
        return {
            **report,
            "status": "ERROR",
            "sync": "failed",
            "error_code": "provider",
            "feed_used": feed,
            "remediation": str(exc),
        }
    after = data_check(settings, feed=feed, as_of=now)
    return {
        **after,
        "sync": status,
        "inserted": inserted,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "rows_fetched": fetched,
        "provider_requests": len(calls),
        "request_plan": [
            {
                "symbols": list(symbols),
                "start": start.isoformat(),
                "end": stop.isoformat(),
                "feed": requested_feed,
            }
            for symbols, start, stop, requested_feed in calls
        ],
        "warnings": warnings,
        "feed_used": feed,
        "revision_audit": revision_audit,
        "note": (
            "Revision audit re-fetched stored bars."
            if revision_audit
            else "Missing-data sync only. No feed fallback and no broker client."
        ),
    }


def _missing_intervals(window: list[date], stored: set[date]) -> list[tuple[date, date]]:
    groups: list[list[date]] = []
    current: list[date] = []
    for session in window:
        if session in stored:
            if current:
                groups.append(current)
                current = []
            continue
        current.append(session)
    if current:
        groups.append(current)
    return [(group[0], group[-1]) for group in groups]


def _required_window(end: date) -> list[date]:
    cal = sessions_between(end - timedelta(days=900), end)
    eligible = [s for s in cal if modeled_available_at(s) <= modeled_available_at(end)]
    if len(eligible) <= _WARMUP:
        return eligible
    return eligible[-_WARMUP:]


def _live_fetcher(settings: Settings) -> Fetcher:
    key = settings.alpaca_api_key
    secret = settings.alpaca_api_secret
    if key is None or secret is None:
        raise RuntimeError(
            "Alpaca credentials are not configured. data-sync is opt-in and read-only."
        )
    from nomadquant.marketdata.alpaca_bars import AlpacaDailyBars

    client = AlpacaDailyBars(key.get_secret_value(), secret.get_secret_value())
    return client.fetch
