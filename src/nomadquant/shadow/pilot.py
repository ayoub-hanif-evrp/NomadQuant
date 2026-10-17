"""Forward-pilot monitoring from persisted shadow rows. No invented trades."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
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
    store = ShadowStore.open_readonly(path)
    if store is None:
        return {
            "initialized": False,
            "status": "NOT_STARTED",
            "caveat": _CAVEAT,
            "hypothetical_fills": 0,
            "prospective_decisions": 0,
            "supervision": supervised_readiness(settings),
        }
    snap = store.snapshot()
    valuation = value_forward_portfolio(snap, settings.market_data_path)
    reconcile = run_reconcile(settings)
    totals = store.history_totals()
    recent = store.list_cycles(limit=30)
    forward_recent = [row for row in recent if row.get("label") in {None, "forward_shadow"}]
    prospective_recent = [
        row
        for row in forward_recent
        if row.get("status") not in {"missed_signal", "blocked"} and _created_after_signal(row)
    ]
    fills_total = int(totals["forward_by_status"].get("filled", 0))
    missed_total = int(totals["forward_by_status"].get("missed_signal", 0))
    failed_total = int(totals["forward_by_status"].get("error", 0)) + int(
        totals["forward_by_status"].get("blocked", 0)
    )
    pilot_raw = store.get_meta(PILOT_STARTED_KEY)
    pilot_day = _pilot_day(pilot_raw)
    now = datetime.now(UTC)
    eligible = _eligible_sessions(pilot_day, now)
    processed = {
        row.get("signal_session") for row in prospective_recent if row.get("signal_session")
    }
    pending = store.pending_intents()
    sample = forward_recent[:verify_limit]
    verified = []
    failures = 0
    for row in sample:
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
        "status": "INCONCLUSIVE" if fills_total == 0 else "OBSERVING",
        "pilot_started_at": pilot_raw,
        "days_since_start": None if pilot_day is None else (now.date() - pilot_day).days,
        "eligible_sessions": len(eligible),
        "sessions_processed": len(processed),
        "sessions_missed": missed_total,
        "sessions_awaiting_data": len(pending),
        "failed_cycles": failed_total,
        "pending_intents": int(totals["pending_intents"]),
        "history_totals": totals,
        "reconciliation_ok": bool(reconcile.get("ok")),
        "verified_cycles": len([row for row in verified if row["status"] == "PASS"]),
        "verification_failures": failures,
        "verification_sample": {
            "checked": len(verified),
            "passed": len([row for row in verified if row["status"] == "PASS"]),
            "failed": failures,
            "limit": verify_limit,
            "history_cycles": totals["cycles_total"],
            "note": "Counts in this object are a recent sample, not the full history.",
        },
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
        "prospective_decisions": len(prospective_recent),
        "prospective_decisions_are_recent": True,
        "hypothetical_fills": fills_total,
        "fill_assumption": "delayed_hypothetical_daily_open",
        "baseline": baseline,
        "hypothesis": {
            "strategy_id": "spy_tsmom_12_1",
            "parameters_unchanged": True,
            "comparison": "inconclusive" if fills_total == 0 else "observing",
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
            for row in forward_recent
        ],
        "equity_history": store.equity_history(limit=500),
        "caveat": _CAVEAT,
        "supervision": supervised_readiness(settings),
    }


def supervised_readiness(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    """Read-only answer to whether a forward shadow pilot may be started.

    Does not create a ledger, sync market data, or apply a fill.
    """
    from nomadquant.shadow.data_ops import data_check
    from nomadquant.shadow.gate import application_guard
    from nomadquant.shadow.preflight import run_preflight

    clock = now or datetime.now(UTC)
    coverage = data_check(settings, feed="sip", as_of=clock)
    preflight = run_preflight(settings, as_of=clock)
    reconcile = run_reconcile(settings)
    guard = application_guard(settings)
    path = Path(settings.shadow_path)
    pending: list[dict[str, Any]] = []
    pilot_raw = None
    cash = None
    if path.exists():
        store = ShadowStore.open_readonly(path)
        if store is not None:
            pending = store.pending_intents()
            pilot_raw = store.get_meta(PILOT_STARTED_KEY)
            cash = str(store.snapshot()["cash_usd"])
    data_status = str(coverage.get("status") or "UNKNOWN")
    data_complete = data_status == "OK" and int(coverage.get("missing_count") or 0) == 0
    data_fresh = data_complete
    checks = {
        str(item.get("name")): item
        for item in list(preflight.get("checks") or [])
        if isinstance(item, dict)
    }
    rebalance_scheduled = bool(checks.get("rebalance_due", {}).get("ok"))
    signal_eligible = bool(checks.get("eligible_signal_session", {}).get("ok"))
    observation_available = bool(checks.get("observation", {}).get("ok"))
    signal_session = preflight.get("signal_session")
    recovery = bool(preflight.get("recovery_required")) or any(
        str(item.get("state") or item.get("status") or "") == "RESERVED" for item in pending
    )
    eligible_pending = _eligible_pending(pending, settings)
    worker_script = Path(__file__).resolve().parents[3] / "scripts" / "shadow-daily.ps1"
    lock = Path(settings.shadow_path).parent / "shadow_worker.lock"
    pilot_running = False
    if lock.exists():
        age = clock - datetime.fromtimestamp(lock.stat().st_mtime, tz=UTC)
        pilot_running = age < timedelta(hours=2)
    failed_daily = 0
    if path.exists():
        reader = ShadowStore.open_readonly(path)
        if reader is not None:
            failed_daily = int(reader.history_totals()["failed_daily_operations"])
    reasons: list[str] = []
    if not path.exists():
        reasons.append("ledger_missing")
    if not data_complete:
        reasons.append(f"market_data:{data_status}")
    if path.exists() and not reconcile.get("ok"):
        reasons.append("ledger_not_reconciled")
    if not guard.get("allowed"):
        reasons.extend(f"guard:{item}" for item in list(guard.get("reasons") or []))
    if preflight.get("status") == "BLOCKED":
        reasons.append("preflight_blocked")
    if recovery:
        reasons.append("recovery_required")
    if pending and not eligible_pending:
        reasons.append("pending_observation_not_executable")
    if not pilot_raw:
        reasons.append("pilot_clock_unset")
    proposal_ready = eligible_pending > 0
    awaiting_approval = proposal_ready and not _has_live_fill_grant(path, clock)
    state = _pilot_state(
        configured=path.exists(),
        recovery=recovery,
        blocked=preflight.get("status") == "BLOCKED"
        or not guard.get("allowed")
        or (path.exists() and not reconcile.get("ok")),
        data_complete=data_complete,
        pending=len(pending),
        eligible_pending=eligible_pending,
        rebalance_scheduled=rebalance_scheduled,
        failed_daily=failed_daily,
        clock_started=pilot_raw is not None,
        awaiting_approval=awaiting_approval,
    )
    return {
        "readiness": state,
        "state": state,
        "as_of": clock.isoformat(),
        "signal_session": signal_session if rebalance_scheduled else None,
        "reasons": reasons,
        "data_status": data_status,
        "data_complete": data_complete,
        "data_fresh": data_fresh,
        "rebalance_scheduled": rebalance_scheduled,
        "signal_eligible": signal_eligible,
        "observation_available": observation_available,
        "pending_intent_count": len(pending),
        "pending_intent_eligible_count": eligible_pending,
        "pending_can_resume": eligible_pending > 0,
        "pending_intents": len(pending),
        "recovery_required": recovery,
        "global_application_allowed": bool(guard.get("allowed")),
        "ledger_reconciled": bool(reconcile.get("ok")) if path.exists() else False,
        "pilot_clock_started": pilot_raw is not None,
        "pilot_worker_configured": worker_script.exists(),
        "pilot_running": pilot_running,
        "shadow_fill_model": "delayed_hypothetical_daily_open",
        "user_confirmation_required": pilot_raw is None,
        "armable": (
            pilot_raw is None
            and state
            in {
                "READY_TO_START",
                "WAITING_FOR_SESSION",
                "WAITING_FOR_DATA",
            }
        )
        or awaiting_approval,
        "lifecycle": _lifecycle(
            state=state,
            clock_started=pilot_raw is not None,
            pending=len(pending),
            proposal_ready=proposal_ready,
            awaiting_approval=awaiting_approval,
        ),
        "preflight_status": preflight.get("status"),
        "application_blocked": not bool(guard.get("allowed")),
        "guard_reasons": list(guard.get("reasons") or []),
        "next_execution": "delayed_hypothetical",
        "realtime_executable": False,
        "user_decision_required": pilot_raw is None,
        "pilot_started_at": pilot_raw,
        "pilot_active": pilot_running,
        "cash_usd": cash,
        "mutates_forward_ledger": False,
        "broker_orders": False,
        "note": _STATE_NOTES.get(state, ""),
    }


_STATE_NOTES = {
    "NOT_CONFIGURED": "The forward ledger file is absent. Inspection does not create it.",
    "READY_TO_START": (
        "Today's month-start signal can be recorded. Arming the pilot does not need "
        "the next session's opening price. A simulated fill still waits for that open "
        "and a separate approval."
    ),
    "WAITING_FOR_SESSION": (
        "No month-start rebalance is due. You can still arm the pilot so future "
        "month-start sessions are recorded. That does not create an October trade."
    ),
    "WAITING_FOR_DATA": "Stored SIP coverage is incomplete for the required window.",
    "PENDING_OBSERVATION": (
        "A recorded signal is waiting for the next session's opening price. "
        "Presence alone does not make it executable."
    ),
    "AWAITING_USER_APPROVAL": (
        "A sized proposal is ready. Approve the exact internal-shadow operation "
        "before a simulated fill. This is not an Alpaca order."
    ),
    "PILOT_ARMED": (
        "The forward clock is set. Future month-start sessions can be recorded. "
        "No simulated fill has been authorized yet."
    ),
    "BLOCKED": "A guard, reconcile failure, or preflight block prevents application.",
    "RECOVERY_REQUIRED": "An interrupted reservation must be recovered before a new apply.",
    "OBSERVING": (
        "The pilot clock has started. A start timestamp does not mean a worker is running."
    ),
    "FAILED": "A recorded daily operation failed.",
}


def _pilot_state(
    *,
    configured: bool,
    recovery: bool,
    blocked: bool,
    data_complete: bool,
    pending: int,
    eligible_pending: int,
    rebalance_scheduled: bool,
    failed_daily: int,
    clock_started: bool,
    awaiting_approval: bool = False,
) -> str:
    """The month-start signal is recordable on its own session.

    The next session's open is needed for the simulated fill, not for recording the
    decision, so it is never a precondition for READY_TO_START or for arming the clock.
    """
    if not configured:
        return "NOT_CONFIGURED"
    if recovery:
        return "RECOVERY_REQUIRED"
    if blocked:
        return "BLOCKED"
    if not data_complete:
        return "WAITING_FOR_DATA"
    if failed_daily:
        return "FAILED"
    if awaiting_approval:
        return "AWAITING_USER_APPROVAL"
    if pending and eligible_pending == 0:
        return "PENDING_OBSERVATION"
    if rebalance_scheduled and not pending:
        return "READY_TO_START"
    if clock_started:
        return "PILOT_ARMED"
    return "WAITING_FOR_SESSION"


def _lifecycle(
    *,
    state: str,
    clock_started: bool,
    pending: int,
    proposal_ready: bool,
    awaiting_approval: bool,
) -> str:
    if state in {"NOT_CONFIGURED", "BLOCKED", "RECOVERY_REQUIRED", "FAILED", "WAITING_FOR_DATA"}:
        return state
    if awaiting_approval:
        return "AWAITING_USER_APPROVAL"
    if proposal_ready:
        return "PROPOSAL_READY"
    if pending:
        return "PENDING_EXECUTION_OBSERVATION"
    if state == "READY_TO_START":
        return "SIGNAL_ELIGIBLE"
    if clock_started:
        return "PILOT_ARMED"
    return "UNARMED"


def _has_live_fill_grant(path: Path, now: datetime) -> bool:
    if not path.exists():
        return False
    store = ShadowStore.open_readonly(path)
    if store is None:
        return False
    raw = store.get_meta("shadow_apply_approval")
    if not raw:
        return False
    try:
        record = json.loads(raw)
        expires = datetime.fromisoformat(str(record["expires_at"]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return False
    if record.get("status") != "pending":
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires > now


def _eligible_pending(pending: list[dict[str, Any]], settings: Settings) -> int:
    """Count pending intents whose fill session bar is already stored. Presence is not enough."""
    market_path = Path(settings.market_data_path)
    if not market_path.exists():
        return 0
    market = MarketStore.open_readonly(market_path)
    if market is None or not market.has_symbol(SYMBOL, FEED):
        return 0
    stored = set(market.sessions(SYMBOL, FEED))
    count = 0
    for item in pending:
        raw = item.get("fill_session")
        if not raw:
            continue
        try:
            session = date.fromisoformat(str(raw))
        except ValueError:
            continue
        if session in stored and str(item.get("state")) == "PENDING_DATA":
            count += 1
    return count


def pilot_start_preview(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    """Read-only preview. Does not start the pilot or mutate the ledger."""
    import hashlib

    readiness = supervised_readiness(settings, now=now)
    path = Path(settings.shadow_path)
    snapshot: dict[str, Any] | None = None
    if path.exists():
        opened = ShadowStore.open_readonly(path)
        if opened is not None:
            snap = opened.snapshot()
            snapshot = {
                "version": snap["version"],
                "cash_usd": str(snap["cash_usd"]),
                "reserved_cash_usd": str(snap["reserved_cash_usd"]),
                "holdings": {key: str(value) for key, value in snap["holdings"].items()},
            }
    from nomadquant.risk.policy import RiskPolicy
    from nomadquant.shadow.approval import market_fingerprint

    policy = RiskPolicy()
    body = {
        "state": readiness["state"],
        "snapshot": snapshot,
        "policy_version": policy.version,
        "policy_hash": policy.policy_hash(),
        "data_complete": readiness["data_complete"],
        "pending_intent_count": readiness["pending_intent_count"],
        "pending_intent_eligible_count": readiness["pending_intent_eligible_count"],
        "rebalance_scheduled": readiness["rebalance_scheduled"],
        "signal_session": readiness["signal_session"],
        "signal_eligible": readiness["signal_eligible"],
        "observation_available": readiness["observation_available"],
        "execution_model": "delayed_hypothetical_daily_open",
        "realtime_executable": False,
        "files_that_would_change": [
            str(path),
            str(Path(settings.risk_path)),
            str(Path(settings.shadow_path).parent / "shadow_logs"),
        ],
        "would_create_pilot_clock": readiness["pilot_clock_started"] is False and path.exists(),
        "recovery": "nomadquant-shadow recover releases an interrupted reservation only.",
        "cannot_undo": (
            "A committed simulated fill and the pilot clock are forward history. "
            "There is no automatic undo."
        ),
        "broker_orders": False,
        "mutates_forward_ledger": False,
        "market_fingerprint": market_fingerprint(Path(settings.market_data_path)),
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["preview_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    body["approval_token"] = body["preview_hash"]
    return body


def confirm_pilot_start(
    settings: Settings, approval: str, *, now: datetime | None = None
) -> dict[str, Any]:
    """Arm the forward clock and optionally store a fill grant. Never a broker order."""
    from nomadquant.shadow.approval import (
        current_binding,
        issue_shadow_approval,
        market_fingerprint,
        state_can_be_approved,
        state_can_be_armed,
    )
    from nomadquant.shadow.missed import PILOT_STARTED_KEY

    clock = now or datetime.now(UTC)
    current = pilot_start_preview(settings, now=clock)
    rejected = {
        "applied": False,
        "stored": False,
        "broker_orders": False,
        "scope": "internal_shadow_simulation_only",
    }
    if approval != current["preview_hash"]:
        return {
            **rejected,
            "status": "REJECTED",
            "reason": "approval token does not match the current preview",
        }
    state = str(current["state"])
    may_arm = state_can_be_armed(state)
    may_grant = state_can_be_approved(state)
    if not may_arm and not may_grant:
        return {
            **rejected,
            "status": "REJECTED",
            "reason": f"state {state} cannot arm the pilot or receive a fill grant",
            "state": state,
        }
    again = pilot_start_preview(settings, now=clock)
    if again["preview_hash"] != approval:
        return {
            **rejected,
            "status": "REJECTED",
            "reason": "state changed between preview and confirmation",
        }
    path = Path(settings.shadow_path)
    if not path.exists():
        return {**rejected, "status": "REJECTED", "reason": "shadow ledger is not initialized"}
    store = ShadowStore(path, namespace="forward")
    armed = False
    if store.get_meta(PILOT_STARTED_KEY) is None and may_arm:
        store.set_meta(PILOT_STARTED_KEY, clock.isoformat())
        armed = True
    record: dict[str, Any] | None = None
    if may_grant:
        from nomadquant.risk.policy import RiskPolicy

        policy = RiskPolicy()
        snap = store.snapshot()
        binding = current_binding(
            ledger_version=int(snap["version"]),
            policy=policy,
            market_fingerprint=market_fingerprint(Path(settings.market_data_path)),
            preview_hash=approval,
        )
        try:
            record = issue_shadow_approval(store, binding, now=clock)
        except ValueError as exc:
            if not armed:
                return {**rejected, "status": "REJECTED", "reason": str(exc)}
    if not armed and record is None:
        return {
            **rejected,
            "status": "REJECTED",
            "reason": "the forward clock is already set and no fill grant was stored",
            "state": state,
        }
    return {
        "status": "PILOT_ARMED" if record is None else "CONFIRMATION_ACCEPTED",
        "applied": False,
        "stored": True,
        "preview_hash": approval,
        "state": "PILOT_ARMED" if record is None else state,
        "expires_at": None if record is None else record["expires_at"],
        "fill_grant_issued": record is not None,
        "pilot_clock_started": True,
        "scope": "internal_shadow_simulation_only",
        "broker_orders": False,
        "next_command": (
            "nomadquant-shadow worker --mode inspect"
            if record is None
            else "nomadquant-shadow worker --mode shadow-apply"
        ),
        "note": (
            "The forward clock is set so future month-start sessions can be recorded. "
            if record is None
            else "A one-time internal-shadow fill grant is stored. "
        )
        + "This is not an Alpaca order authorization and it does not enable scheduled applies.",
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
