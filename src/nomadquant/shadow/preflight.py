"""Forward shadow preflight and reconcile. Never submits broker orders."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from nomadquant.config import Settings
from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore
from nomadquant.shadow.cycle import FEED, LOOKBACK, SKIP, STRATEGY_ID, SYMBOL
from nomadquant.shadow.marks import value_forward_portfolio
from nomadquant.shadow.store import LABEL_FORWARD, ShadowStore

PreflightStatus = Literal[
    "READY",
    "WAITING_FOR_DATA",
    "NO_REBALANCE_DUE",
    "ALREADY_PROCESSED",
    "BLOCKED",
    "ERROR",
]


def run_preflight(settings: Settings, *, as_of: datetime | None = None) -> dict[str, Any]:
    now = as_of or datetime.now(UTC)
    checks: list[dict[str, Any]] = []
    status: PreflightStatus = "READY"

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    # 1. Locked paper-only
    capital = Decimal(str(settings.initial_virtual_capital_usd))
    paper_ok = (
        settings.trading_mode == "paper"
        and settings.allow_order_submission is False
        and capital == Decimal("100")
    )
    add(
        "paper_only_locks",
        paper_ok,
        f"mode={settings.trading_mode} orders={settings.allow_order_submission} capital={capital}",
    )
    if not paper_ok:
        status = "BLOCKED"

    # 2. Valid $100 shadow account
    shadow_path = Path(settings.shadow_path)
    store = ShadowStore(shadow_path, namespace="forward")
    store.recover_interrupted()
    snap = store.snapshot()
    capital_ok = snap["starting_capital_usd"] == Decimal("100") and snap["cash_usd"] >= 0
    add(
        "shadow_account",
        capital_ok,
        f"cash={snap['cash_usd']} reserved={snap['reserved_cash_usd']} version={snap['version']}",
    )
    if not capital_ok:
        status = "BLOCKED"

    # 8. Unrecovered reservations
    active = store.list_active_reservations()
    add(
        "no_stuck_reservations",
        len(active) == 0,
        f"active_reservations={len(active)}",
    )
    if active:
        status = "BLOCKED"

    # 3–6. Market data
    market_path = Path(settings.market_data_path)
    if not market_path.exists():
        add("market_database", False, "market.sqlite missing")
        return _result("WAITING_FOR_DATA", checks, now, store, snap)

    market = MarketStore(market_path)
    has = market.has_symbol(SYMBOL, FEED)
    add("symbol_feed_coverage", has, f"{SYMBOL}/{FEED}")
    if not has:
        return _result("WAITING_FOR_DATA", checks, now, store, snap)

    sessions = sorted(market.sessions(SYMBOL, FEED))
    if len(sessions) < LOOKBACK + SKIP + 5:
        add(
            "warmup_window",
            False,
            f"need>={LOOKBACK + SKIP} sessions; have {len(sessions)}",
        )
        return _result("WAITING_FOR_DATA", checks, now, store, snap)
    add("warmup_window", True, f"sessions={len(sessions)}")

    cal = sessions_between(sessions[0], sessions[-1])
    eligible = [s for s in cal if modeled_available_at(s) <= now and s in set(sessions)]
    if not eligible:
        add("eligible_signal_session", False, "none available yet")
        return _result("WAITING_FOR_DATA", checks, now, store, snap)

    signal_day = eligible[-1]
    add(
        "eligible_signal_session",
        True,
        f"{signal_day.isoformat()} available_at={modeled_available_at(signal_day).isoformat()}",
    )

    # 11. Duplicate / already processed
    cycle_key = f"{LABEL_FORWARD}:{FEED}:{SYMBOL}:{signal_day.isoformat()}:{STRATEGY_ID}"
    if store.cycle_exists(cycle_key):
        add("cycle_eligibility", False, f"already processed {cycle_key}")
        return _result("ALREADY_PROCESSED", checks, now, store, snap, signal_day=signal_day)

    # Month-start rebalance?
    prior = [s for s in cal if s < signal_day]
    is_rebalance = (not prior) or prior[-1].month != signal_day.month
    if not is_rebalance:
        add("rebalance_due", False, "not a month-start session")
        # Still READY for dry-run observation of no-trade, but flag.
        status = "NO_REBALANCE_DUE"
    else:
        add("rebalance_due", True, "month-start rebalance window")

    # 10. Next open observation
    next_sessions = [s for s in cal if s > signal_day and s in set(sessions)]
    if not next_sessions:
        add("observation", False, "next session open not in store")
        if status == "READY":
            status = "WAITING_FOR_DATA"
    else:
        fill_day = next_sessions[0]
        rows = list(market.session_ohlc(SYMBOL, FEED, fill_day, fill_day))
        has_open = bool(rows)
        add(
            "observation",
            has_open,
            f"fill_session={fill_day} open={'yes' if has_open else 'missing'}",
        )
        if not has_open and status == "READY":
            status = "WAITING_FOR_DATA"

    # 7. Strategy / policy hashes (static for now)
    add(
        "strategy_config",
        True,
        f"{STRATEGY_ID} lookback={LOOKBACK} skip={SKIP} feed={FEED}",
    )

    # 12. Shadow mode enforcement
    add(
        "no_order_enforcement",
        settings.allow_order_submission is False,
        "ALLOW_ORDER_SUBMISSION=false required",
    )

    if any(
        not c["ok"] for c in checks if c["name"] in {"paper_only_locks", "no_order_enforcement"}
    ):
        status = "BLOCKED"

    return _result(status, checks, now, store, snap, signal_day=signal_day)


def run_reconcile(settings: Settings) -> dict[str, Any]:
    store = ShadowStore(settings.shadow_path, namespace="forward")
    store.recover_interrupted()
    snap = store.snapshot()
    valuation = value_forward_portfolio(snap, settings.market_data_path)
    issues: list[str] = []
    if snap["cash_usd"] < 0:
        issues.append("negative_cash")
    if snap["reserved_cash_usd"] > snap["cash_usd"]:
        issues.append("reserved_exceeds_cash")
    for sym, qty in snap["holdings"].items():
        if qty < 0:
            issues.append(f"short_{sym}")
    if valuation.status == "ok" and valuation.equity_usd is not None:
        expected = snap["cash_usd"] + sum(p.market_value_usd for p in valuation.positions)
        if expected != valuation.equity_usd:
            issues.append("equity_mismatch")
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "snapshot": {
            "cash_usd": str(snap["cash_usd"]),
            "reserved_cash_usd": str(snap["reserved_cash_usd"]),
            "holdings": {k: str(v) for k, v in snap["holdings"].items()},
            "version": snap["version"],
        },
        "valuation": valuation.as_dict(),
        "active_reservations": store.list_active_reservations(),
        "note": "Shadow ledger reconcile only. Not Alpaca. No broker orders.",
    }


def _result(
    status: PreflightStatus,
    checks: list[dict[str, Any]],
    now: datetime,
    store: ShadowStore,
    snap: dict[str, Any],
    signal_day: Any = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "as_of": now.isoformat(),
        "checks": checks,
        "signal_session": None if signal_day is None else str(signal_day),
        "ledger_version": snap["version"],
        "cash_usd": str(snap["cash_usd"]),
        "cycle_count": store.count_cycles(),
        "trading_state": "SHADOW_ONLY",
        "allow_order_submission": False,
        "note": "Preflight for internal shadow simulator only. Never submits broker orders.",
    }
