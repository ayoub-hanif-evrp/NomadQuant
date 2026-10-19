"""Forward shadow preflight and reconcile. Inspect-only — never mutates ledger."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from nomadquant.config import Settings
from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.report import market_data_status
from nomadquant.marketdata.store import MarketStore
from nomadquant.shadow.cycle import FEED, LOOKBACK, SKIP, STRATEGY_ID, SYMBOL
from nomadquant.shadow.marks import value_forward_portfolio
from nomadquant.shadow.pending import awaited_fill_session
from nomadquant.shadow.store import LABEL_FORWARD, MigrationRequired, ShadowStore


def _read_store(path: str) -> ShadowStore:
    try:
        store = ShadowStore.open_readonly(path)
    except MigrationRequired as exc:
        raise MigrationRequired("MIGRATION_REQUIRED") from exc
    if store is None:
        raise MigrationRequired("shadow ledger is missing")
    return store


PreflightStatus = Literal[
    "READY",
    "WAITING_FOR_DATA",
    "NO_REBALANCE_DUE",
    "ALREADY_PROCESSED",
    "BLOCKED",
    "ERROR",
]


def observation_waiting_detail(
    fill_day: date,
    available_at: datetime,
    *,
    rebalance_due: bool,
) -> str:
    """Describe a future open without inventing a pending trade."""
    detail = (
        f"fill_session={fill_day.isoformat()} open=not_yet_available "
        f"(expected after {available_at.isoformat()})"
    )
    if rebalance_due:
        return f"{detail}; the signal is recorded as pending until then"
    return f"{detail}; no month-start rebalance is due, so no signal is waiting"


def run_preflight(settings: Settings, *, as_of: datetime | None = None) -> dict[str, Any]:
    now = as_of or datetime.now(UTC)
    checks: list[dict[str, Any]] = []
    status: PreflightStatus = "READY"

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

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

    shadow_file = Path(settings.shadow_path)
    if not shadow_file.exists():
        add("shadow_account", False, "shadow ledger not initialized")
        return {
            "status": "WAITING_FOR_DATA" if status != "BLOCKED" else "BLOCKED",
            "as_of": now.isoformat(),
            "checks": checks,
            "signal_session": None,
            "ledger_version": None,
            "cash_usd": None,
            "cycle_count": 0,
            "recovery_required": False,
            "pending_intent_count": 0,
            "outbox_backlog": 0,
            "trading_state": "SHADOW_ONLY",
            "allow_order_submission": False,
            "initialized": False,
            "note": "Shadow ledger is not created. GET inspection does not initialize it.",
        }

    try:
        store = _read_store(settings.shadow_path)
    except MigrationRequired:
        return {
            "status": "MIGRATION_REQUIRED",
            "as_of": now.isoformat(),
            "checks": checks,
            "initialized": False,
            "trading_state": "SHADOW_ONLY",
            "allow_order_submission": False,
            "note": "Shadow schema is old. Inspection did not migrate it.",
        }
    recovery = store.recovery_status()
    snap = store.snapshot()
    capital_ok = snap["starting_capital_usd"] == Decimal("100") and snap["cash_usd"] >= 0
    add(
        "shadow_account",
        capital_ok,
        f"cash={snap['cash_usd']} reserved={snap['reserved_cash_usd']} version={snap['version']}",
    )
    if not capital_ok:
        status = "BLOCKED"

    active = recovery["active_reservations"]
    add(
        "no_stuck_reservations",
        len(active) == 0,
        f"active_reservations={len(active)}; recovery_required={recovery['recovery_required']}",
    )
    if active:
        status = "BLOCKED"

    market_path = Path(settings.market_data_path)
    if not market_path.exists():
        add("market_database", False, "market.sqlite missing")
        return _result("WAITING_FOR_DATA", checks, now, store, snap, recovery)

    market = MarketStore(market_path)
    has = market.has_symbol(SYMBOL, FEED)
    add("symbol_feed_coverage", has, f"{SYMBOL}/{FEED}")
    if not has:
        return _result("WAITING_FOR_DATA", checks, now, store, snap, recovery)

    sessions = sorted(market.sessions(SYMBOL, FEED))
    if len(sessions) < LOOKBACK + SKIP + 5:
        add(
            "warmup_window",
            False,
            f"need>={LOOKBACK + SKIP} sessions; have {len(sessions)}",
        )
        return _result("WAITING_FOR_DATA", checks, now, store, snap, recovery)
    add("warmup_window", True, f"sessions={len(sessions)}")

    # Calendar completeness for strategy warm-up window (not mere row count).
    warm_start = sessions[-(LOOKBACK + SKIP + 5)]
    md = market_data_status(
        str(market_path),
        start=warm_start,
        end=sessions[-1],
        symbols=[SYMBOL],
        feed=FEED,
    )
    coverage_ok = md.coverage_complete and md.suitable_for_research
    add(
        "calendar_coverage",
        coverage_ok,
        (
            f"complete={md.coverage_complete} suitable={md.suitable_for_research} "
            f"warnings={len(md.warnings)}"
            if md.requested_start
            else "no requested research window recorded — INCOMPLETE"
        ),
    )
    if not md.requested_start or not coverage_ok:
        # Do not green-wash: row count alone is insufficient.
        if status == "READY":
            status = "WAITING_FOR_DATA"

    cal = sessions_between(sessions[0], sessions[-1])
    eligible = [s for s in cal if modeled_available_at(s) <= now and s in set(sessions)]
    if not eligible:
        add("eligible_signal_session", False, "none available yet")
        return _result("WAITING_FOR_DATA", checks, now, store, snap, recovery)

    signal_day = eligible[-1]
    add(
        "eligible_signal_session",
        True,
        f"{signal_day.isoformat()} available_at={modeled_available_at(signal_day).isoformat()}",
    )

    cycle_key = f"{LABEL_FORWARD}:{FEED}:{SYMBOL}:{signal_day.isoformat()}:{STRATEGY_ID}"
    if store.cycle_exists(cycle_key):
        add("cycle_eligibility", False, f"already processed {cycle_key}")
        return _result(
            "ALREADY_PROCESSED", checks, now, store, snap, recovery, signal_day=signal_day
        )

    prior = [s for s in cal if s < signal_day]
    is_rebalance = (not prior) or prior[-1].month != signal_day.month
    if not is_rebalance:
        add("rebalance_due", False, "not a month-start session")
        status = "NO_REBALANCE_DUE"
    else:
        add("rebalance_due", True, "month-start rebalance window")

    fill_day = awaited_fill_session(signal_day)
    if fill_day is None:
        add("observation", False, "next session unresolved")
        if status == "READY":
            status = "WAITING_FOR_DATA"
    else:
        rows = list(market.session_ohlc(SYMBOL, FEED, fill_day, fill_day))
        has_open = bool(rows)
        fill_due = modeled_available_at(fill_day) <= now
        if has_open:
            detail = f"fill_session={fill_day} open=yes"
        elif fill_due:
            detail = f"fill_session={fill_day} open=missing"
        else:
            detail = observation_waiting_detail(
                fill_day,
                modeled_available_at(fill_day),
                rebalance_due=is_rebalance,
            )
        add("observation", has_open, detail)
        if not has_open and fill_due and status == "READY":
            status = "WAITING_FOR_DATA"

    add(
        "strategy_config",
        True,
        f"{STRATEGY_ID} lookback={LOOKBACK} skip={SKIP} feed={FEED}",
    )
    add(
        "no_order_enforcement",
        settings.allow_order_submission is False,
        "ALLOW_ORDER_SUBMISSION=false required",
    )

    lock_names = {"paper_only_locks", "no_order_enforcement"}
    if any(not c["ok"] for c in checks if c["name"] in lock_names):
        status = "BLOCKED"

    return _result(status, checks, now, store, snap, recovery, signal_day=signal_day)


def run_reconcile(settings: Settings) -> dict[str, Any]:
    """Inspect-only reconcile. Does not release reservations or mutate ledger."""
    if not Path(settings.shadow_path).exists():
        return {
            "ok": False,
            "issues": ["shadow_uninitialized"],
            "recovery_required": False,
            "snapshot": None,
            "valuation": None,
            "active_reservations": [],
            "outbox_backlog": 0,
            "initialized": False,
            "note": "Shadow ledger is not created. Inspection does not initialize it.",
        }
    store = _read_store(settings.shadow_path)
    recovery = store.recovery_status()
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
    if recovery["recovery_required"]:
        issues.append("recovery_required")
    if valuation.status == "ok" and valuation.equity_usd is not None:
        expected = snap["cash_usd"] + sum(p.market_value_usd for p in valuation.positions)
        if expected != valuation.equity_usd:
            issues.append("equity_mismatch")
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "recovery_required": recovery["recovery_required"],
        "snapshot": {
            "cash_usd": str(snap["cash_usd"]),
            "reserved_cash_usd": str(snap["reserved_cash_usd"]),
            "holdings": {k: str(v) for k, v in snap["holdings"].items()},
            "version": snap["version"],
        },
        "valuation": valuation.as_dict(),
        "active_reservations": recovery["active_reservations"],
        "outbox_backlog": recovery["outbox_backlog"],
        "note": (
            "Inspect-only reconcile. Run nomadquant-shadow recover to release "
            "stuck reservations. Not Alpaca. No broker orders."
        ),
    }


def _result(
    status: PreflightStatus,
    checks: list[dict[str, Any]],
    now: datetime,
    store: ShadowStore,
    snap: dict[str, Any],
    recovery: dict[str, Any],
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
        "recovery_required": recovery["recovery_required"],
        "pending_intent_count": recovery["pending_intent_count"],
        "outbox_backlog": recovery["outbox_backlog"],
        "trading_state": "SHADOW_ONLY",
        "allow_order_submission": False,
        "note": (
            "Inspect-only preflight. Never mutates ledger/reservations. "
            "Never submits broker orders."
        ),
    }
