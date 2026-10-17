"""Plain-language status for the home screen and Copilot. Read-only."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from nomadquant.config import Settings
from nomadquant.marketdata.availability import latest_completed_session, latest_safe_session
from nomadquant.marketdata.calendar import (
    is_early_close,
    is_session,
    next_session,
    sessions_between,
)

NEW_YORK = ZoneInfo("America/New_York")

STRATEGY_PLAIN = (
    "The strategy looks at SPY once a month, on the first trading day. If SPY rose over the "
    "past 12 months, skipping the most recent month, it holds SPY. Otherwise it holds cash. "
    "A trade is simulated at the next day's open in the internal $100 book."
)


def market_clock(now: datetime) -> dict[str, Any]:
    ny = now.astimezone(NEW_YORK)
    today = ny.date()
    session_today = is_session(today)
    opens = datetime.combine(today, time(9, 30), NEW_YORK)
    closes = datetime.combine(today, time(13 if is_early_close(today) else 16, 0), NEW_YORK)
    if session_today and opens <= ny < closes:
        state, label = "open", "Market open"
    elif session_today and ny < opens:
        state, label = "pre_open", "Market opens today"
    elif session_today:
        state, label = "closed", "Market closed for the day"
    else:
        state, label = "closed", "Market closed today"
    if session_today and ny < opens:
        next_open = opens
    else:
        next_open = datetime.combine(next_session(today), time(9, 30), NEW_YORK)
    return {
        "now_utc": now.astimezone(UTC).isoformat(),
        "now_new_york": ny.isoformat(),
        "today": today.isoformat(),
        "weekday": ny.strftime("%A"),
        "is_trading_day": session_today,
        "state": state,
        "label": label,
        "next_open": next_open.isoformat(),
        "last_completed_session": latest_completed_session(now).isoformat(),
    }


def next_rebalance(today: date) -> dict[str, str]:
    """First NYSE session of this month if still ahead, otherwise of next month."""
    year, month = today.year, today.month
    for _ in range(3):
        first = sessions_between(date(year, month, 1), date(year, month, 10))[0]
        if first >= today:
            return {
                "signal_session": first.isoformat(),
                "fill_session": next_session(first).isoformat(),
            }
        month += 1
        if month == 13:
            year, month = year + 1, 1
    raise RuntimeError("No month-start session found.")


def overview(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    from nomadquant.shadow.data_ops import data_check
    from nomadquant.shadow.pilot import forward_pilot_report, supervised_readiness

    current = now or datetime.now(UTC)
    clock = market_clock(current)
    try:
        eligible = latest_safe_session(current, "sip").isoformat()
    except Exception:  # noqa: BLE001 - the screen must still explain itself
        eligible = None
    coverage = data_check(settings, feed="sip")
    spy = (coverage.get("symbols") or {}).get("SPY") or {}
    stored = spy.get("latest_stored")
    missing = list(spy.get("missing_sessions") or [])
    data_current = bool(stored) and stored == eligible
    readiness = supervised_readiness(settings, now=current)
    report = forward_pilot_report(settings)
    rebalance = next_rebalance(date.fromisoformat(clock["today"]))
    fills = int(report.get("hypothetical_fills") or 0)
    decisions = list(report.get("decisions") or [])[:5]
    pilot_started = bool(readiness.get("pilot_clock_started"))
    rebalance_due = bool(readiness.get("rebalance_scheduled"))

    checks = [
        {
            "key": "data",
            "ok": data_current,
            "title": "Market data is up to date" if data_current else "Market data is behind",
            "detail": (
                f"Stored SPY daily bars include {stored}, the latest finished trading day."
                if data_current
                else f"Stored SPY daily bars end on {stored}. "
                f"The latest finished trading day is {eligible}."
            ),
            "action": None if data_current else "sync",
        },
        {
            "key": "pilot",
            "ok": pilot_started,
            "title": "Forward pilot is running"
            if pilot_started
            else "Forward pilot has not been started",
            "detail": (
                "Simulated trades can be recorded in the $100 book."
                if pilot_started
                else "The system checks each day, but it will not record a simulated trade "
                "until you start the pilot."
            ),
            "action": None if pilot_started else "start_pilot",
        },
        {
            "key": "rebalance",
            "ok": rebalance_due,
            "title": "A monthly rebalance is due" if rebalance_due else "No rebalance is due yet",
            "detail": (
                f"The strategy trades only on the first trading day of a month. The next one is "
                f"{rebalance['signal_session']}, with a simulated fill at the open on "
                f"{rebalance['fill_session']}."
            ),
            "action": None,
        },
    ]
    if fills:
        headline = f"{fills} simulated trade{'s' if fills != 1 else ''} recorded"
        summary = "The internal book has simulated fills. No Alpaca order was sent."
    else:
        headline = "No trades yet, and that is expected"
        summary = (
            f"The system checked {len(decisions)} recent trading day"
            f"{'s' if len(decisions) != 1 else ''} and correctly did nothing. "
            f"The earliest possible simulated trade is at the open on {rebalance['fill_session']}."
        )
    return {
        "clock": clock,
        "data": {
            "feed": "sip",
            "latest_stored": stored,
            "latest_eligible": eligible,
            "missing_sessions": missing,
            "current": data_current,
        },
        "trading": {
            "headline": headline,
            "summary": summary,
            "checks": checks,
            "state": readiness.get("state"),
            "lifecycle": readiness.get("lifecycle"),
            "armable": bool(readiness.get("armable")),
            "pilot_clock_started": bool(readiness.get("pilot_clock_started")),
            "next_rebalance": rebalance,
            "recent_decisions": [
                {
                    "id": item.get("id"),
                    "session": item.get("signal_session"),
                    "result": "No trade"
                    if item.get("intent") == "no_trade"
                    else item.get("intent"),
                }
                for item in decisions
            ],
            "simulated_fills": fills,
            "alpaca_orders": "disabled",
        },
        "portfolio": {
            "starting_usd": report.get("starting_capital_usd") or "100",
            "equity_usd": report.get("equity_usd") or readiness.get("cash_usd"),
            "cash_usd": report.get("cash_usd") or readiness.get("cash_usd"),
            "holdings": report.get("holdings") or {},
            "simulated_fills": fills,
        },
        "strategy": {"id": "spy_tsmom_12_1", "plain": STRATEGY_PLAIN},
        "broker_orders": False,
    }
