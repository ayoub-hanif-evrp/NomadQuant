"""Forward-pilot monitoring from persisted shadow rows. No invented trades."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.marketdata.availability import latest_safe_session, modeled_available_at
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore
from nomadquant.shadow.cycle import FEED, SYMBOL
from nomadquant.shadow.marks import value_forward_portfolio
from nomadquant.shadow.missed import PILOT_STARTED_KEY
from nomadquant.shadow.preflight import run_reconcile
from nomadquant.shadow.store import ShadowStore
from nomadquant.shadow.verify import verify_cycle

_CAVEAT = (
    "Raw daily closes are not total returns. A delayed hypothetical open fill "
    "is not a real-time execution. A short forward sample cannot support alpha, "
    "Sharpe confidence, or a claim that the pre-registered backtest was confirmed."
)


def forward_pilot_report(settings: Settings, *, verify_limit: int = 5) -> dict[str, Any]:
    path = Path(settings.shadow_path)
    if not path.exists():
        return {
            "initialized": False,
            "status": "NOT_STARTED",
            "caveat": _CAVEAT,
            "hypothetical_fills": 0,
            "prospective_decisions": 0,
            "supervision": supervised_readiness(settings),
        }
    store = ShadowStore(path, namespace="forward")
    snap = store.snapshot()
    valuation = value_forward_portfolio(snap, settings.market_data_path)
    reconcile = run_reconcile(settings)
    cycles = store.list_cycles(limit=500)
    forward = [row for row in cycles if row.get("label") in {None, "forward_shadow"}]
    missed = [row for row in forward if row.get("status") == "missed_signal"]
    fills = [row for row in forward if row.get("status") == "filled"]
    failed = [row for row in forward if row.get("status") in {"error", "blocked"}]
    prospective = [
        row
        for row in forward
        if row.get("status") not in {"missed_signal", "blocked"} and _created_after_signal(row)
    ]
    pilot_raw = store.get_meta(PILOT_STARTED_KEY)
    pilot_day = _pilot_day(pilot_raw)
    now = datetime.now(UTC)
    eligible = _eligible_sessions(pilot_day, now)
    processed = {row.get("signal_session") for row in prospective if row.get("signal_session")}
    pending = store.pending_intents()
    verified = []
    failures = 0
    for row in forward[:verify_limit]:
        if row.get("id") is None:
            continue
        try:
            report = verify_cycle(settings, int(row["id"]))
            status = str(report["status"])
        except Exception:  # noqa: BLE001
            status = "INVALID_ARTIFACT"
        verified.append({"cycle_id": row["id"], "status": status})
        if status == "FAIL":
            failures += 1
    peak = snap["peak_equity_usd"]
    equity = valuation.equity_usd
    drawdown = None
    if equity is not None and peak > 0:
        drawdown = str(((peak - equity) / peak).quantize(Decimal("0.000001")))
    baseline = _baseline(settings, pilot_day)
    return {
        "initialized": True,
        "status": "INCONCLUSIVE" if not fills else "OBSERVING",
        "pilot_started_at": pilot_raw,
        "days_since_start": None if pilot_day is None else (now.date() - pilot_day).days,
        "eligible_sessions": len(eligible),
        "sessions_processed": len(processed),
        "sessions_missed": len({row.get("signal_session") for row in missed}),
        "sessions_awaiting_data": len(pending),
        "failed_cycles": len(failed),
        "pending_intents": len(pending),
        "reconciliation_ok": bool(reconcile.get("ok")),
        "verified_cycles": len([row for row in verified if row["status"] == "PASS"]),
        "verification_failures": failures,
        "recent_verification": verified,
        "starting_capital_usd": "100",
        "equity_usd": None if equity is None else str(equity),
        "cash_usd": str(snap["cash_usd"]),
        "holdings": {key: str(value) for key, value in snap["holdings"].items()},
        "realized_pnl_usd": str(snap["realized_pnl_usd"]),
        "unrealized_pnl_usd": (
            None if valuation.unrealized_pnl_usd is None else str(valuation.unrealized_pnl_usd)
        ),
        "total_costs_usd": str(snap["total_costs_usd"]),
        "exposure_usd": None if valuation.exposure_usd is None else str(valuation.exposure_usd),
        "drawdown_fraction": drawdown,
        "prospective_decisions": len(prospective),
        "hypothetical_fills": len(fills),
        "fill_assumption": "delayed_hypothetical_daily_open",
        "baseline": baseline,
        "hypothesis": {
            "strategy_id": "spy_tsmom_12_1",
            "parameters_unchanged": True,
            "comparison": "inconclusive" if not fills else "observing",
            "cash_baseline_usd": "100",
            "note": _CAVEAT,
        },
        "decisions": [
            {
                "id": row.get("id"),
                "signal_session": row.get("signal_session"),
                "status": row.get("status"),
                "intent": row.get("intent"),
                "created_at": row.get("created_at"),
                "fill_price": row.get("fill_price"),
                "forward_created": _created_after_signal(row),
            }
            for row in forward[:30]
        ],
        "equity_history": store.equity_history(limit=500),
        "caveat": _CAVEAT,
        "supervision": supervised_readiness(settings),
    }


def supervised_readiness(settings: Settings) -> dict[str, Any]:
    """Read-only answer to whether a forward shadow pilot may be started.

    Does not create a ledger, sync market data, or apply a fill.
    """
    from nomadquant.shadow.data_ops import data_check
    from nomadquant.shadow.gate import application_guard
    from nomadquant.shadow.preflight import run_preflight

    coverage = data_check(settings, feed="sip")
    preflight = run_preflight(settings)
    reconcile = run_reconcile(settings)
    guard = application_guard(settings)
    path = Path(settings.shadow_path)
    pending: list[dict[str, Any]] = []
    pilot_raw = None
    cash = None
    if path.exists():
        store = ShadowStore(path, namespace="forward")
        pending = store.pending_intents()
        pilot_raw = store.get_meta(PILOT_STARTED_KEY)
        cash = str(store.snapshot()["cash_usd"])
    data_status = str(coverage.get("status") or "UNKNOWN")
    data_fresh = data_status in {"OK", "CURRENT", "COMPLETE"}
    reasons: list[str] = []
    if not data_fresh:
        reasons.append(f"market_data:{data_status}")
    if not reconcile.get("ok"):
        reasons.append("ledger_not_reconciled")
    if not guard.get("allowed"):
        reasons.extend(f"guard:{item}" for item in list(guard.get("reasons") or []))
    if preflight.get("status") == "BLOCKED":
        reasons.append("preflight_blocked")
    if not pilot_raw:
        reasons.append("pilot_clock_unset")
    if reasons and (not data_fresh):
        readiness = "INSUFFICIENT_DATA"
    elif any(
        item.startswith("guard:") or item in {"ledger_not_reconciled", "preflight_blocked"}
        for item in reasons
    ):
        readiness = "BLOCKED"
    elif not pilot_raw:
        readiness = "READY"
    else:
        readiness = "OBSERVING"
    return {
        "readiness": readiness,
        "reasons": reasons,
        "data_status": data_status,
        "data_fresh": data_fresh,
        "rebalance_due": preflight.get("status") not in {"NO_REBALANCE_DUE", "ALREADY_PROCESSED"},
        "preflight_status": preflight.get("status"),
        "pending_can_resume": len(pending) > 0,
        "pending_intents": len(pending),
        "ledger_reconciled": bool(reconcile.get("ok")),
        "application_blocked": not bool(guard.get("allowed")),
        "guard_reasons": list(guard.get("reasons") or []),
        "next_execution": "delayed_hypothetical",
        "realtime_executable": False,
        "user_decision_required": pilot_raw is None,
        "pilot_started_at": pilot_raw,
        "pilot_active": pilot_raw is not None,
        "cash_usd": cash,
        "mutates_forward_ledger": False,
        "broker_orders": False,
        "note": (
            "READY means the checks that can be answered are clear enough to ask "
            "for an explicit shadow-apply. It is not an active trading system, "
            "and this report does not submit an Alpaca order or mutate the ledger."
        ),
    }


def _created_after_signal(row: dict[str, Any]) -> bool:
    raw_session = row.get("signal_session")
    raw_created = row.get("created_at")
    if not raw_session or not raw_created:
        return False
    try:
        created = datetime.fromisoformat(str(raw_created))
        available = modeled_available_at(date.fromisoformat(str(raw_session)))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created >= available


def _pilot_day(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date()


def _eligible_sessions(pilot_day: date | None, now: datetime) -> list[date]:
    if pilot_day is None:
        return []
    try:
        end = latest_safe_session(now, FEED)
    except Exception:  # noqa: BLE001
        return []
    if end < pilot_day:
        return []
    return sessions_between(pilot_day, end)


def _baseline(settings: Settings, pilot_day: date | None) -> dict[str, Any]:
    empty = {
        "status": "inconclusive",
        "reason": (
            "No forward fill has been recorded, so strategy and buy-and-hold are not comparable."
        ),
        "spy_raw_close_return": None,
        "adjustment": "raw",
        "not_total_return": True,
    }
    if pilot_day is None or not Path(settings.market_data_path).exists():
        return empty
    market = MarketStore.open_readonly(settings.market_data_path)
    if market is None or not market.has_symbol(SYMBOL, FEED):
        return empty
    sessions = sorted(market.sessions(SYMBOL, FEED))
    window = [session for session in sessions if session >= pilot_day]
    if len(window) < 2:
        return empty
    start_bar = market.session_bar(SYMBOL, FEED, window[0])
    end_bar = market.session_bar(SYMBOL, FEED, window[-1])
    if start_bar is None or end_bar is None or start_bar.close == 0:
        return empty
    change = (end_bar.close - start_bar.close) / start_bar.close
    return {
        "status": "descriptive_only",
        "reason": (
            "SPY raw close change over the pilot window. Not a total return and not "
            "the shadow fill model."
        ),
        "spy_raw_close_return": str(change.quantize(Decimal("0.000001"))),
        "from_session": window[0].isoformat(),
        "to_session": window[-1].isoformat(),
        "adjustment": "raw",
        "not_total_return": True,
        "comparable_to_shadow_fills": False,
    }
