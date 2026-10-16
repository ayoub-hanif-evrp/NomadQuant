"""Daily shadow research cycle with observation-based chronology.

Never submits broker orders. Uses the internal $100 shadow ledger only.
Reservations and fills are authoritative in the shadow DB (not cross-DB atomic).
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore
from nomadquant.research.models import CostModel
from nomadquant.research.signals import momentum_return, target_from_momentum
from nomadquant.risk import (
    AccountMetrics,
    InternalLedger,
    Proposal,
    RiskEngine,
    RiskPolicy,
    RiskStore,
)
from nomadquant.shadow.store import (
    ConcurrentModificationError,
    ShadowStore,
    ShadowStoreError,
    namespace_for_label,
    shadow_path_for_label,
)

STRATEGY_ID = "spy_tsmom_12_1"
SYMBOL = "SPY"
FEED = "sip"
LOOKBACK = 252
SKIP = 21
LABEL_FORWARD = "forward_shadow"
LABEL_RETRO = "retrospective_replay"
_NY = ZoneInfo("America/New_York")

_ZERO = Decimal("0")
_ONE = Decimal("1")

# How far in the past a signal_session override may be for forward_shadow.
_FORWARD_SIGNAL_MAX_AGE = timedelta(days=5)


def run_shadow_cycle(
    *,
    market_path: str | Path,
    shadow_path: str | Path,
    risk_path: str | Path,
    mode: str = "dry-run",
    as_of: datetime | None = None,
    signal_session: date | None = None,
    label: str = LABEL_FORWARD,
    policy: RiskPolicy | None = None,
) -> dict[str, Any]:
    """Run one shadow cycle. Idempotent on ``cycle_key``.

    Modes:
    - dry-run: compute intent + risk; never mutate ledger or record fills
    - apply: may reserve and simulate a fill only when observation exists

    Chronology:
    1. Signal from eligible completed bars
    2. Pending intent until next-session open is observed/retrieved
    3. Risk re-eval with observation timestamp (never backdated to signal)
    4. Reserve in shadow DB → simulated fill → accounting
    """
    started = time.monotonic()
    now = as_of or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("as_of must be timezone-aware.")
    if label not in {LABEL_FORWARD, LABEL_RETRO}:
        raise ValueError(f"Unknown label {label!r}.")
    if mode not in {"dry-run", "apply"}:
        raise ValueError(f"Unknown mode {mode!r}.")

    # Chronology gate: forward + past signal_session override is not prospective.
    if label == LABEL_FORWARD and signal_session is not None:
        signal_avail = modeled_available_at(signal_session)
        if now - signal_avail > _FORWARD_SIGNAL_MAX_AGE:
            return {
                "id": None,
                "cycle_key": f"blocked:{label}:{signal_session}",
                "created_at": datetime.now(UTC).isoformat(),
                "mode": mode,
                "label": label,
                "status": "blocked",
                "intent": "no_trade",
                "warnings": [
                    "Forward shadow refuses a past --signal-session override. "
                    "Use --label retrospective_replay for historical simulation "
                    "(writes to a separate ledger)."
                ],
                "evidence": {
                    "reason": "chronology_violation",
                    "signal_session": signal_session.isoformat(),
                    "signal_available_at": signal_avail.isoformat(),
                    "as_of": now.isoformat(),
                },
                "evidence_hash": "",
                "error_safe": "chronology_violation",
                "feed": FEED,
                "symbol": SYMBOL,
                "risk_reasons": [],
                "ledger_before": {},
                "ledger_after": {},
                "duration_ms": _ms(started),
            }

    db_path = shadow_path_for_label(shadow_path, label)
    shadow = ShadowStore(db_path, namespace=namespace_for_label(label))
    # Recovery is explicit (`nomadquant-shadow recover` / worker recover).
    # Apply must not silently release another worker's reservation.

    from nomadquant.shadow.outbox import deliver_outbox
    from nomadquant.shadow.pending import awaited_fill_session, resume_pending_intents

    # 0.1 — Resume unresolved intents chronologically before any new signal.
    resumed = resume_pending_intents(
        shadow=shadow,
        market_path=market_path,
        risk_path=risk_path,
        mode=mode,
        now=now,
        label=label,
        policy=policy,
    )
    if mode == "apply" and resumed:
        deliver_outbox(shadow, risk_path)

    before = shadow.snapshot()
    warnings: list[str] = []
    if resumed:
        warnings.append(f"Resumed {len(resumed)} pending intent(s) before new signal.")
    market = MarketStore(market_path)
    if not market.has_symbol(SYMBOL, FEED):
        if resumed:
            return {**resumed[-1], "prior_resumes": resumed, "warnings": warnings}
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="insufficient_data",
            intent="no_trade",
            warnings=["No local market bars for SPY/SIP."],
            evidence={"reason": "missing_market_data"},
            duration_ms=_ms(started),
            mutate=False,
        )

    stored_sessions = sorted(market.sessions(SYMBOL, FEED))
    if not stored_sessions:
        if resumed:
            return {**resumed[-1], "prior_resumes": resumed, "warnings": warnings}
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="insufficient_data",
            intent="no_trade",
            warnings=["Empty session set for stored SPY/SIP coverage."],
            evidence={},
            duration_ms=_ms(started),
            mutate=False,
        )

    sessions = sessions_between(stored_sessions[0], stored_sessions[-1])
    signal_day = signal_session or _latest_eligible_signal_session(sessions, now)
    if signal_day is None:
        if resumed:
            return {**resumed[-1], "prior_resumes": resumed, "warnings": warnings}
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="insufficient_data",
            intent="no_trade",
            warnings=["No eligible completed signal session is available yet."],
            evidence={"now": now.isoformat()},
            duration_ms=_ms(started),
            mutate=False,
        )

    cycle_key = f"{label}:{FEED}:{SYMBOL}:{signal_day.isoformat()}:{STRATEGY_ID}"
    if shadow.cycle_exists(cycle_key) and mode == "apply":
        existing = shadow.get_cycle_by_key(cycle_key)
        assert existing is not None
        existing["warnings"] = list(existing.get("warnings") or []) + [
            "Duplicate apply prevented; returning prior cycle."
        ]
        if resumed:
            existing["prior_resumes"] = resumed
        return existing

    ohlc = {
        session: (o, h, low, c)
        for session, o, h, low, c in market.session_ohlc(
            SYMBOL, FEED, stored_sessions[0], stored_sessions[-1]
        )
    }
    closes = {session: close for session, (_o, _h, _l, close) in ohlc.items()}
    mom = momentum_return(closes, sessions, signal_day, LOOKBACK, SKIP)
    if mom is None:
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="insufficient_data",
            intent="no_trade",
            warnings=[
                f"INSUFFICIENT_DATA: momentum_return requires lookback={LOOKBACK} "
                f"+ skip={SKIP} sessions; warm-up incomplete for {signal_day}."
            ],
            evidence={
                "reason": "insufficient_momentum_window",
                "signal_session": signal_day.isoformat(),
                "lookback_sessions": LOOKBACK,
                "skip_sessions": SKIP,
                "prior_resumes": resumed,
            },
            duration_ms=_ms(started),
            mutate=False,
            signal_session=signal_day,
        )
    target = target_from_momentum(mom)
    is_rebalance = _is_month_start(signal_day, sessions)
    current_qty = before["holdings"].get(SYMBOL, _ZERO)
    mark = closes.get(signal_day)
    if mark is None:
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="insufficient_data",
            intent="no_trade",
            warnings=[f"Missing close for signal session {signal_day}."],
            evidence={"signal_session": signal_day.isoformat()},
            duration_ms=_ms(started),
            mutate=False,
            signal_session=signal_day,
        )

    equity = before["cash_usd"] + current_qty * mark
    current_weight = (current_qty * mark / equity) if equity > 0 else _ZERO
    if not is_rebalance:
        intent = "hold"
        target = current_weight.quantize(Decimal("0.000001"))
    elif target == current_weight:
        intent = "hold"
    elif target > current_weight:
        intent = "buy"
    elif target < current_weight:
        intent = "sell"
    else:
        intent = "hold"

    decision_produced_at = datetime.now(UTC)
    evidence: dict[str, Any] = {
        "strategy_id": STRATEGY_ID,
        "lookback_sessions": LOOKBACK,
        "skip_sessions": SKIP,
        "signal_session": signal_day.isoformat(),
        "signal_available_at": modeled_available_at(signal_day).isoformat(),
        "decision_produced_at": decision_produced_at.isoformat(),
        "momentum": None if mom is None else str(mom),
        "target_weight": str(target),
        "current_weight": str(current_weight),
        "is_month_start_rebalance": is_rebalance,
        "feed": FEED,
        "symbol": SYMBOL,
        "mark_close": str(mark),
        "label": label,
        "mode": mode,
        "namespace": shadow.namespace,
        "shadow_db": str(db_path),
    }

    intent_id = f"intent:{cycle_key}"
    if intent in {"hold"} or not is_rebalance:
        if mode == "apply":
            shadow.upsert_intent(
                intent_id=intent_id,
                cycle_key=cycle_key,
                state="NO_TRADE",
                strategy_id=STRATEGY_ID,
                feed=FEED,
                symbol=SYMBOL,
                evidence=evidence,
                evidence_hash=_hash(evidence),
                signal_session=signal_day.isoformat(),
                target_weight=str(target),
                from_state="SIGNAL_RECORDED",
                reason="No rebalance or hold",
                ledger_version=before["version"],
            )
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="no_trade",
            intent=intent if is_rebalance else "no_trade",
            warnings=warnings
            + ([] if is_rebalance else ["Not a month-start session; no rebalance."]),
            evidence=evidence,
            duration_ms=_ms(started),
            mutate=mode == "apply",
            signal_session=signal_day,
            momentum=mom,
            target_weight=target,
            record_equity=mode == "apply",
            mark_price=mark,
        )

    # Await next NYSE session even when its bars are not stored yet.
    fill_day = awaited_fill_session(signal_day) or _next_session(sessions, signal_day)
    if fill_day is None:
        evidence["execution_model"] = "pending_observation"
        if mode == "apply":
            shadow.upsert_intent(
                intent_id=intent_id,
                cycle_key=cycle_key,
                state="PENDING_DATA",
                strategy_id=STRATEGY_ID,
                feed=FEED,
                symbol=SYMBOL,
                evidence=evidence,
                evidence_hash=_hash(evidence),
                signal_session=signal_day.isoformat(),
                target_weight=str(target),
                from_state="SIGNAL_RECORDED",
                reason="Next session calendar unavailable",
                ledger_version=before["version"],
            )
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="pending_data",
            intent=intent,
            warnings=["Next session after signal cannot be determined."],
            evidence=evidence,
            duration_ms=_ms(started),
            mutate=False,
            signal_session=signal_day,
            momentum=mom,
            target_weight=target,
        )

    open_bar = ohlc.get(fill_day)
    open_price = None if open_bar is None else open_bar[0]
    if open_price is None:
        evidence["execution_model"] = "pending_observation"
        evidence["fill_session"] = fill_day.isoformat()
        evidence["awaited_fill_session"] = fill_day.isoformat()
        if mode == "apply":
            shadow.upsert_intent(
                intent_id=intent_id,
                cycle_key=cycle_key,
                state="PENDING_DATA",
                strategy_id=STRATEGY_ID,
                feed=FEED,
                symbol=SYMBOL,
                evidence=evidence,
                evidence_hash=_hash(evidence),
                signal_session=signal_day.isoformat(),
                fill_session=fill_day.isoformat(),
                target_weight=str(target),
                from_state="SIGNAL_RECORDED",
                reason="Open price not yet available",
                ledger_version=before["version"],
            )
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="pending_data",
            intent=intent,
            warnings=[f"Open price for fill session {fill_day} is not available."],
            evidence=evidence,
            duration_ms=_ms(started),
            mutate=False,
            signal_session=signal_day,
            fill_session=fill_day,
            momentum=mom,
            target_weight=target,
        )

    # Observation: we retrieve a stored daily open NOW. This is a delayed
    # observation-based simulation — NOT a claim we executed at the open live.
    observation_retrieved_at = now
    # Earliest the open could exist as a completed session: session open bell.
    # We still label delayed because local SQLite has no live tick provenance.
    session_open_ny = datetime(
        fill_day.year, fill_day.month, fill_day.day, 9, 30, tzinfo=_NY
    ).astimezone(UTC)
    observation_as_of = max(session_open_ny, observation_retrieved_at)
    # Never stamp earlier than signal availability either.
    signal_avail = modeled_available_at(signal_day)
    if observation_as_of <= signal_avail:
        observation_as_of = observation_retrieved_at
        if observation_as_of <= signal_avail:
            observation_as_of = signal_avail + timedelta(seconds=1)

    evidence["execution_model"] = "delayed_observation_simulation"
    evidence["observation_retrieved_at"] = observation_retrieved_at.isoformat()
    evidence["observation_as_of"] = observation_as_of.isoformat()
    evidence["price_as_of"] = observation_as_of.isoformat()
    evidence["fill_session"] = fill_day.isoformat()
    evidence["open_price"] = str(open_price)
    evidence["observation_note"] = (
        "Stored daily OHLC open retrieved for delayed simulation. "
        "Not proof of real-time open availability at signal time. "
        "16:30 NY daily-bar model does not establish next-session open timing."
    )

    costs = CostModel(
        commission_usd=Decimal("0"),
        spread_bps=Decimal("1"),
        slippage_bps=Decimal("1"),
        min_notional_usd=Decimal("1"),
        quantity_precision=6,
    )
    from nomadquant.shadow.sizing import size_policy_aware

    active_policy = policy or RiskPolicy()
    sized = size_policy_aware(
        cash=before["cash_usd"],
        reserved=before["reserved_cash_usd"],
        qty=current_qty,
        target_weight=target,
        price=open_price,
        costs=costs,
        policy=active_policy,
    )
    evidence["sizing"] = {
        "desired_target_weight": str(sized.desired_target_weight),
        "feasible_weight": str(sized.feasible_weight),
        "residual_target_weight": str(sized.residual_target_weight),
        "quantity": str(sized.quantity),
        "is_partial": sized.is_partial,
        "reason": sized.reason,
    }
    proposal_qty, side = sized.quantity, sized.side
    if proposal_qty <= 0 or side is None:
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="no_trade",
            intent="no_trade",
            warnings=warnings + [sized.reason],
            evidence=evidence,
            duration_ms=_ms(started),
            mutate=mode == "apply",
            signal_session=signal_day,
            fill_session=fill_day,
            momentum=mom,
            target_weight=target,
            record_equity=mode == "apply",
            mark_price=open_price,
        )

    if side not in {"buy", "sell"}:
        raise RuntimeError("internal: unexpected trade side")
    if sized.is_partial:
        warnings.append(sized.reason)
    proposal = Proposal(
        id=f"shadow:{cycle_key}:{side}:{proposal_qty}",
        source="shadow_cycle",
        symbol=SYMBOL,
        side=side,  # type: ignore[arg-type]
        quantity=proposal_qty,
        as_of=observation_as_of,
    )
    risk_store = RiskStore(risk_path)
    risk_ledger = InternalLedger(
        cash_usd=before["cash_usd"],
        holdings=dict(before["holdings"]),
        capital_usd=Decimal("100"),
        reserved_cash_usd=before["reserved_cash_usd"],
    )
    prices = {
        SYMBOL: {
            "price": open_price,
            "as_of": observation_as_of,
            "feed": FEED,
        }
    }
    exposure = current_qty * open_price
    account = AccountMetrics(
        realized_pnl_today_usd=_ZERO,
        equity_usd=before["cash_usd"] + exposure,
        peak_equity_usd=max(before["peak_equity_usd"], before["cash_usd"] + exposure),
    )
    risk = RiskEngine(policy or RiskPolicy()).evaluate(
        proposal,
        risk_ledger,
        prices,
        store=risk_store,
        account=account,
        now=now,
    )
    evidence["proposal"] = proposal.model_dump(mode="json")
    evidence["risk_verdict"] = risk.verdict
    evidence["risk_reasons"] = risk.reasons

    if risk.verdict != "APPROVE":
        if mode == "apply":
            shadow.upsert_intent(
                intent_id=intent_id,
                cycle_key=cycle_key,
                state="RISK_REJECTED",
                strategy_id=STRATEGY_ID,
                feed=FEED,
                symbol=SYMBOL,
                evidence=evidence,
                evidence_hash=_hash(evidence),
                signal_session=signal_day.isoformat(),
                fill_session=fill_day.isoformat(),
                target_weight=str(target),
                from_state="SIGNAL_RECORDED",
                reason=f"Risk {risk.verdict}",
                source_price=str(open_price),
                price_as_of=observation_as_of.isoformat(),
                risk_verdict=risk.verdict,
                ledger_version=before["version"],
            )
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="risk_rejected" if risk.verdict == "REJECT" else "insufficient_data",
            intent=intent,
            warnings=warnings,
            evidence=evidence,
            duration_ms=_ms(started),
            mutate=mode == "apply",
            signal_session=signal_day,
            fill_session=fill_day,
            momentum=mom,
            target_weight=target,
            proposal_id=proposal.id,
            risk_verdict=risk.verdict,
            risk_reasons=risk.reasons,
            record_equity=mode == "apply",
            mark_price=open_price,
        )

    if mode == "dry-run":
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="dry_run_approved",
            intent=intent,
            warnings=warnings
            + [
                "Dry-run only; ledger not mutated; no broker order.",
                "APPROVE is not an execution.",
            ],
            evidence=evidence,
            duration_ms=_ms(started),
            mutate=False,
            signal_session=signal_day,
            fill_session=fill_day,
            momentum=mom,
            target_weight=target,
            proposal_id=proposal.id,
            risk_verdict=risk.verdict,
            risk_reasons=risk.reasons,
        )

    # Apply: reserve in shadow DB → simulate fill → commit with OCC.
    reserve_amt = risk.notional_usd or _ZERO
    if side == "sell":
        reserve_amt = _ZERO
    try:
        if reserve_amt > 0:
            shadow.reserve_cash(
                intent_id=intent_id,
                amount=reserve_amt,
                expected_version=before["version"],
                cycle_key=cycle_key,
            )
            before = shadow.snapshot()
        else:
            shadow.upsert_intent(
                intent_id=intent_id,
                cycle_key=cycle_key,
                state="RISK_APPROVED",
                strategy_id=STRATEGY_ID,
                feed=FEED,
                symbol=SYMBOL,
                evidence=evidence,
                evidence_hash=_hash(evidence),
                signal_session=signal_day.isoformat(),
                fill_session=fill_day.isoformat(),
                target_weight=str(target),
                from_state="SIGNAL_RECORDED",
                reason="Approved sell / zero reserve",
                source_price=str(open_price),
                price_as_of=observation_as_of.isoformat(),
                risk_verdict=risk.verdict,
                ledger_version=before["version"],
            )
    except ConcurrentModificationError as exc:
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="error",
            intent=intent,
            warnings=warnings,
            evidence=evidence,
            duration_ms=_ms(started),
            mutate=False,
            signal_session=signal_day,
            fill_session=fill_day,
            momentum=mom,
            target_weight=target,
            proposal_id=proposal.id,
            risk_verdict=risk.verdict,
            error_safe=f"OCC conflict on reserve: {exc}",
        )
    except ShadowStoreError as exc:
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="error",
            intent=intent,
            warnings=warnings,
            evidence=evidence,
            duration_ms=_ms(started),
            mutate=False,
            signal_session=signal_day,
            fill_session=fill_day,
            momentum=mom,
            target_weight=target,
            proposal_id=proposal.id,
            risk_verdict=risk.verdict,
            error_safe=f"Reservation failed: {exc}",
        )

    after, fill_meta = _simulate_fill(before, side, proposal_qty, open_price, costs)
    # Clear reserve into the fill cash path (buy already debits full cash).
    after["reserved_cash_usd"] = _ZERO
    evidence["fill"] = fill_meta
    evidence["outbox_note"] = (
        "Risk audit is projected via shadow_outbox only AFTER shadow commit. "
        "Risk DB is not financial truth."
    )
    outbox = {
        "kind": "risk_evaluation",
        "payload": {
            "proposal_id": proposal.id,
            "source": "shadow_cycle",
            "symbol": SYMBOL,
            "side": side,
            "quantity": str(proposal_qty),
            "verdict": risk.verdict,
            "reasons": risk.reasons,
            "policy_version": risk.policy_version,
            "policy_hash": risk.policy_hash,
            "notional_usd": None if risk.notional_usd is None else str(risk.notional_usd),
            "proposal_as_of": observation_as_of.isoformat(),
            "evaluated_at": now.isoformat(),
            "cycle_key": cycle_key,
        },
    }
    # Do NOT write risk_store before shadow commit — outbox delivers after.
    detail = _finish(
        shadow,
        mode=mode,
        label=label,
        before=before,
        after=after,
        status="filled",
        intent=intent,
        warnings=warnings,
        evidence=evidence,
        duration_ms=_ms(started),
        mutate=True,
        signal_session=signal_day,
        fill_session=fill_day,
        momentum=mom,
        target_weight=target,
        proposal_id=proposal.id,
        risk_verdict=risk.verdict,
        risk_reasons=risk.reasons,
        fill_price=open_price,
        fill_qty=proposal_qty,
        fill_side=side,
        costs_usd=Decimal(fill_meta["costs_usd"]),
        record_equity=True,
        mark_price=open_price,
        cycle_key=cycle_key,
        expected_version=before["version"],
        commit_reservation_intent_id=intent_id if reserve_amt > 0 else None,
        outbox=outbox,
    )
    deliver_outbox(shadow, risk_path)
    return detail


def _simulate_fill(
    before: dict[str, Any],
    side: str,
    qty: Decimal,
    open_price: Decimal,
    costs: CostModel,
) -> tuple[dict[str, Any], dict[str, str]]:
    half = open_price * (costs.spread_bps + costs.slippage_bps) / Decimal(20000)
    fill = open_price + half if side == "buy" else open_price - half
    commission = costs.commission_usd
    notional = qty * fill
    cost_attr = qty * half + commission
    cash = before["cash_usd"]
    holdings = dict(before["holdings"])
    basis = dict(before["cost_basis"])
    realized = before["realized_pnl_usd"]
    if side == "buy":
        cash -= notional + commission
        prev = holdings.get(SYMBOL, _ZERO)
        prev_basis = basis.get(SYMBOL, _ZERO)
        new_qty = prev + qty
        basis[SYMBOL] = ((prev_basis * prev) + notional) / new_qty if new_qty > 0 else _ZERO
        holdings[SYMBOL] = new_qty
    else:
        cash += notional - commission
        prev = holdings.get(SYMBOL, _ZERO)
        prev_basis = basis.get(SYMBOL, _ZERO)
        realized += (fill - prev_basis) * qty - commission
        holdings[SYMBOL] = prev - qty
        if holdings[SYMBOL] <= 0:
            holdings.pop(SYMBOL, None)
            basis.pop(SYMBOL, None)
    if cash < 0:
        raise ValueError("Fill would make cash negative.")
    equity = cash + holdings.get(SYMBOL, _ZERO) * open_price
    after = {
        "cash_usd": cash,
        "reserved_cash_usd": _ZERO,
        "holdings": holdings,
        "cost_basis": basis,
        "realized_pnl_usd": realized,
        "total_costs_usd": before["total_costs_usd"] + cost_attr,
        "peak_equity_usd": max(before["peak_equity_usd"], equity),
    }
    meta = {
        "fill_price": str(fill),
        "open_price": str(open_price),
        "quantity": str(qty),
        "side": side,
        "costs_usd": str(cost_attr),
        "note": (
            "Simulated delayed next-session open fill; not an Alpaca order. "
            "Not a claim of real-time execution at the open."
        ),
    }
    return after, meta


def _delta_quantity(
    *,
    cash: Decimal,
    qty: Decimal,
    target_weight: Decimal,
    price: Decimal,
    costs: CostModel,
) -> tuple[Decimal, str | None]:
    equity = cash + qty * price
    if equity <= 0 or price <= 0:
        return _ZERO, None
    target_value = equity * target_weight
    current_value = qty * price
    delta = target_value - current_value
    if abs(delta) < costs.min_notional_usd:
        return _ZERO, None
    if delta > 0:
        fill = price * (1 + (costs.spread_bps + costs.slippage_bps) / Decimal(20000))
        budget = cash - costs.commission_usd
        spend = min(delta, budget)
        q = (spend / fill).quantize(Decimal(10) ** -costs.quantity_precision, rounding=ROUND_DOWN)
        return (q, "buy") if q > 0 else (_ZERO, None)
    fill = price * (1 - (costs.spread_bps + costs.slippage_bps) / Decimal(20000))
    sell_value = -delta
    q = min(
        qty,
        (sell_value / fill).quantize(Decimal(10) ** -costs.quantity_precision, rounding=ROUND_DOWN),
    )
    return (q, "sell") if q > 0 else (_ZERO, None)


def _finish(
    shadow: ShadowStore,
    *,
    mode: str,
    label: str,
    before: dict[str, Any],
    status: str,
    intent: str,
    warnings: list[str],
    evidence: dict[str, Any],
    duration_ms: int,
    mutate: bool,
    after: dict[str, Any] | None = None,
    signal_session: date | None = None,
    fill_session: date | None = None,
    momentum: Decimal | None = None,
    target_weight: Decimal | None = None,
    proposal_id: str | None = None,
    risk_verdict: str | None = None,
    risk_reasons: list[str] | None = None,
    fill_price: Decimal | None = None,
    fill_qty: Decimal | None = None,
    fill_side: str | None = None,
    costs_usd: Decimal | None = None,
    record_equity: bool = False,
    mark_price: Decimal | None = None,
    error_safe: str = "",
    cycle_key: str | None = None,
    expected_version: int | None = None,
    commit_reservation_intent_id: str | None = None,
    outbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = cycle_key or (
        f"{label}:{FEED}:{SYMBOL}:"
        f"{(signal_session or date.min).isoformat()}:{STRATEGY_ID}:{status}:{mode}"
    )
    evidence_hash = _hash(evidence)
    created = datetime.now(UTC).isoformat()
    ledger_after = after or before
    payload = {
        "created_at": created,
        "mode": mode,
        "label": label,
        "signal_session": None if signal_session is None else signal_session.isoformat(),
        "fill_session": None if fill_session is None else fill_session.isoformat(),
        "feed": FEED,
        "symbol": SYMBOL,
        "status": status,
        "intent": intent,
        "target_weight": None if target_weight is None else str(target_weight),
        "momentum": None if momentum is None else str(momentum),
        "proposal_id": proposal_id,
        "risk_verdict": risk_verdict,
        "risk_reasons": risk_reasons or [],
        "fill_price": None if fill_price is None else str(fill_price),
        "fill_qty": None if fill_qty is None else str(fill_qty),
        "fill_side": fill_side,
        "costs_usd": None if costs_usd is None else str(costs_usd),
        "evidence": evidence,
        "evidence_hash": evidence_hash,
        "warnings": warnings,
        "error_safe": error_safe,
        "duration_ms": duration_ms,
        "ledger_before": _jsonable(before),
        "ledger_after": _jsonable(ledger_after),
        "outbox": outbox,
    }
    equity_point = None
    if record_equity and mark_price is not None:
        held = ledger_after["holdings"].get(SYMBOL, _ZERO)
        exposure = held * mark_price
        equity = ledger_after["cash_usd"] + exposure
        basis = ledger_after["cost_basis"].get(SYMBOL, _ZERO)
        unrealized = (mark_price - basis) * held if held else _ZERO
        equity_point = {
            "recorded_at": created,
            "session": None if signal_session is None else signal_session.isoformat(),
            "equity_usd": equity,
            "cash_usd": ledger_after["cash_usd"],
            "exposure_usd": exposure,
            "realized_pnl_usd": ledger_after["realized_pnl_usd"],
            "unrealized_pnl_usd": unrealized,
        }
        ledger_after = {
            **ledger_after,
            "peak_equity_usd": max(ledger_after["peak_equity_usd"], equity),
        }
        payload["ledger_after"] = _jsonable(ledger_after)

    if shadow.cycle_exists(key):
        existing = shadow.get_cycle_by_key(key)
        assert existing is not None
        return existing

    try:
        will_mutate = mutate and after is not None
        cycle_id = shadow.apply_cycle(
            cycle_key=key,
            payload=payload,
            ledger_after=ledger_after if will_mutate else None,
            equity_point=equity_point if (will_mutate or record_equity) else None,
            expected_version=(expected_version if will_mutate else None),
            commit_reservation_intent_id=commit_reservation_intent_id,
        )
    except ConcurrentModificationError:
        # Release reservation if we held one and fill commit lost the race.
        if commit_reservation_intent_id:
            try:
                shadow.release_reservation(
                    commit_reservation_intent_id,
                    expected_version=shadow.snapshot()["version"],
                )
            except Exception:  # noqa: BLE001
                shadow.recover_interrupted()
        existing = shadow.get_cycle_by_key(key)
        if existing is not None:
            return existing
        raise
    except ShadowStoreError:
        existing = shadow.get_cycle_by_key(key)
        if existing is not None:
            return existing
        raise

    detail = shadow.get_cycle(cycle_id)
    assert detail is not None
    return detail


def _latest_eligible_signal_session(sessions: list[date], now: datetime) -> date | None:
    eligible = [s for s in sessions if modeled_available_at(s) <= now]
    return eligible[-1] if eligible else None


def _next_session(sessions: list[date], current: date) -> date | None:
    for session in sessions:
        if session > current:
            return session
    return None


def _is_month_start(session: date, sessions: list[date]) -> bool:
    prior = [s for s in sessions if s < session]
    if not prior:
        return True
    return prior[-1].month != session.month


def _jsonable(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": snap.get("version"),
        "cash_usd": str(snap["cash_usd"]),
        "reserved_cash_usd": str(snap["reserved_cash_usd"]),
        "holdings": {k: str(v) for k, v in snap["holdings"].items()},
        "cost_basis": {k: str(v) for k, v in snap.get("cost_basis", {}).items()},
        "realized_pnl_usd": str(snap["realized_pnl_usd"]),
        "total_costs_usd": str(snap["total_costs_usd"]),
        "peak_equity_usd": str(snap["peak_equity_usd"]),
        "starting_capital_usd": "100",
    }


def _hash(evidence: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
