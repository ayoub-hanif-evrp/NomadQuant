"""Resume PENDING_DATA intents chronologically before new signals."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore
from nomadquant.research.models import CostModel
from nomadquant.risk import (
    AccountMetrics,
    InternalLedger,
    Proposal,
    RiskEngine,
    RiskPolicy,
    RiskStore,
)
from nomadquant.shadow.provenance import provenance_dict
from nomadquant.shadow.sizing import size_policy_aware
from nomadquant.shadow.store import ShadowStore

_ZERO = Decimal("0")
SYMBOL = "SPY"
FEED = "sip"
STRATEGY_ID = "spy_tsmom_12_1"


def awaited_fill_session(signal_session: date) -> date | None:
    """Next NYSE session after signal, even if bars are not stored yet."""
    lookahead = sessions_between(signal_session, signal_session + timedelta(days=14))
    for session in lookahead:
        if session > signal_session:
            return session
    return None


def resume_pending_intents(
    *,
    shadow: ShadowStore,
    market_path: str | Path,
    risk_path: str | Path,
    mode: str,
    now: datetime,
    label: str,
    policy: RiskPolicy | None = None,
) -> list[dict[str, Any]]:
    """Process unresolved intents oldest-first. Terminal intents are skipped."""
    if mode not in {"dry-run", "apply"}:
        raise ValueError(mode)
    results: list[dict[str, Any]] = []
    market = MarketStore(market_path)
    for intent in shadow.list_pending_intents():
        state = intent.get("state")
        if state not in {"PENDING_DATA", "RISK_APPROVED", "SIGNAL_RECORDED"}:
            # RESERVED is handled by explicit recover / fill path, not silent resume.
            if state == "RESERVED":
                continue
            continue
        result = _resume_one(
            shadow=shadow,
            market=market,
            risk_path=risk_path,
            intent=intent,
            mode=mode,
            now=now,
            label=label,
            policy=policy or RiskPolicy(),
        )
        if result is not None:
            results.append(result)
    return results


def _resume_one(
    *,
    shadow: ShadowStore,
    market: MarketStore,
    risk_path: str | Path,
    intent: dict[str, Any],
    mode: str,
    now: datetime,
    label: str,
    policy: RiskPolicy,
) -> dict[str, Any] | None:
    from nomadquant.shadow.cycle import _finish, _hash, _simulate_fill

    intent_id = intent["intent_id"]
    # Re-read: may have become terminal concurrently.
    current = shadow.get_intent(intent_id)
    if current is None or current["state"] not in {
        "PENDING_DATA",
        "RISK_APPROVED",
        "SIGNAL_RECORDED",
    }:
        return None

    evidence = json.loads(intent["evidence_json"]) if intent.get("evidence_json") else {}
    if isinstance(intent.get("evidence"), dict):
        evidence = intent["evidence"]
    signal_s = intent.get("signal_session") or evidence.get("signal_session")
    if not signal_s:
        return None
    signal_day = date.fromisoformat(str(signal_s))
    fill_s = intent.get("fill_session") or evidence.get("fill_session")
    fill_day = date.fromisoformat(str(fill_s)) if fill_s else awaited_fill_session(signal_day)
    if fill_day is None:
        return {
            "status": "pending_data",
            "intent_id": intent_id,
            "warnings": ["No awaited fill session resolvable."],
        }

    if not market.has_symbol(SYMBOL, FEED):
        return None
    rows = list(market.session_ohlc(SYMBOL, FEED, fill_day, fill_day))
    if not rows:
        # Still waiting — leave PENDING_DATA.
        return {
            "status": "pending_data",
            "intent_id": intent_id,
            "signal_session": signal_day.isoformat(),
            "fill_session": fill_day.isoformat(),
            "warnings": [f"Observation for {fill_day} still unavailable."],
        }

    open_price = Decimal(str(rows[0][1]))  # session, o, h, l, c
    stored_bar = market.session_bar(SYMBOL, FEED, fill_day)
    if stored_bar is None or stored_bar.first_retrieved_at > now:
        return {
            "status": "pending_data",
            "intent_id": intent_id,
            "signal_session": signal_day.isoformat(),
            "fill_session": fill_day.isoformat(),
            "warnings": [
                "Bar provenance is missing or was retrieved after the evaluation clock. "
                "Pending intent kept; not a real-time fill."
            ],
            "evidence_gaps": ["missing_or_late_bar_provenance"],
        }
    observation_retrieved_at = stored_bar.first_retrieved_at
    observation_as_of = observation_retrieved_at
    bar_evidence = provenance_dict(stored_bar, evaluated_at=now)

    before = shadow.snapshot()
    target = Decimal(str(intent.get("target_weight") or evidence.get("target_weight") or "1"))
    costs = CostModel(
        commission_usd=Decimal("0"),
        spread_bps=Decimal("1"),
        slippage_bps=Decimal("1"),
        min_notional_usd=Decimal("1"),
        quantity_precision=6,
    )
    current_qty = before["holdings"].get(SYMBOL, _ZERO)
    sized = size_policy_aware(
        cash=before["cash_usd"],
        reserved=before["reserved_cash_usd"],
        qty=current_qty,
        target_weight=target,
        price=open_price,
        costs=costs,
        policy=policy,
    )
    evidence = {
        **evidence,
        "resumed_at": now.isoformat(),
        "execution_model": bar_evidence["execution_assumption"],
        "realtime_executable": False,
        "observation_retrieved_at": observation_retrieved_at.isoformat(),
        "observation_as_of": observation_as_of.isoformat(),
        "price_as_of": observation_as_of.isoformat(),
        "fill_session": fill_day.isoformat(),
        "open_price": str(open_price),
        "bar_provenance": bar_evidence,
        "sizing": {
            "desired_target_weight": str(sized.desired_target_weight),
            "feasible_weight": str(sized.feasible_weight),
            "residual_target_weight": str(sized.residual_target_weight),
            "quantity": str(sized.quantity),
            "is_partial": sized.is_partial,
            "reason": sized.reason,
        },
        "awaited_fill_session": fill_day.isoformat(),
    }

    if sized.quantity <= 0 or sized.side is None:
        if mode == "apply":
            shadow.upsert_intent(
                intent_id=intent_id,
                cycle_key=intent["cycle_key"],
                state="NO_TRADE",
                strategy_id=STRATEGY_ID,
                feed=FEED,
                symbol=SYMBOL,
                evidence=evidence,
                evidence_hash=_hash(evidence),
                signal_session=signal_day.isoformat(),
                fill_session=fill_day.isoformat(),
                target_weight=str(target),
                from_state=current["state"],
                reason=sized.reason,
                source_price=str(open_price),
                price_as_of=observation_as_of.isoformat(),
                ledger_version=before["version"],
            )
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="no_trade",
            intent="no_trade",
            warnings=[sized.reason],
            evidence=evidence,
            duration_ms=0,
            mutate=mode == "apply",
            signal_session=signal_day,
            fill_session=fill_day,
            target_weight=target,
            cycle_key=f"{intent['cycle_key']}:resumed:no_trade",
        )

    proposal = Proposal(
        id=f"shadow:{intent['cycle_key']}:{sized.side}:{sized.quantity}:resume",
        source="shadow_pending_resume",
        symbol=SYMBOL,
        side=sized.side,  # type: ignore[arg-type]
        quantity=sized.quantity,
        as_of=observation_as_of,
    )
    risk_ledger = InternalLedger(
        cash_usd=before["cash_usd"],
        holdings=dict(before["holdings"]),
        capital_usd=Decimal("100"),
        reserved_cash_usd=before["reserved_cash_usd"],
    )
    prices = {SYMBOL: {"price": open_price, "as_of": observation_as_of, "feed": FEED}}
    exposure = current_qty * open_price
    account = AccountMetrics(
        realized_pnl_today_usd=_ZERO,
        equity_usd=before["cash_usd"] + exposure,
        peak_equity_usd=max(before["peak_equity_usd"], before["cash_usd"] + exposure),
    )
    risk_store = RiskStore(risk_path)
    risk = RiskEngine(policy).evaluate(
        proposal, risk_ledger, prices, store=risk_store, account=account, now=now
    )
    evidence["risk_verdict"] = risk.verdict
    evidence["risk_reasons"] = risk.reasons
    evidence["proposal"] = proposal.model_dump(mode="json")

    if risk.verdict != "APPROVE":
        if mode == "apply":
            shadow.upsert_intent(
                intent_id=intent_id,
                cycle_key=intent["cycle_key"],
                state="RISK_REJECTED",
                strategy_id=STRATEGY_ID,
                feed=FEED,
                symbol=SYMBOL,
                evidence=evidence,
                evidence_hash=_hash(evidence),
                signal_session=signal_day.isoformat(),
                fill_session=fill_day.isoformat(),
                target_weight=str(target),
                from_state=current["state"],
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
            intent=sized.side,
            warnings=[],
            evidence=evidence,
            duration_ms=0,
            mutate=mode == "apply",
            signal_session=signal_day,
            fill_session=fill_day,
            target_weight=target,
            proposal_id=proposal.id,
            risk_verdict=risk.verdict,
            risk_reasons=risk.reasons,
            cycle_key=f"{intent['cycle_key']}:resumed:{risk.verdict}",
        )

    if mode == "dry-run":
        return _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="dry_run_approved",
            intent=sized.side,
            warnings=["Pending resume dry-run; ledger not mutated."],
            evidence=evidence,
            duration_ms=0,
            mutate=False,
            signal_session=signal_day,
            fill_session=fill_day,
            target_weight=target,
            proposal_id=proposal.id,
            risk_verdict=risk.verdict,
            risk_reasons=risk.reasons,
            cycle_key=f"{intent['cycle_key']}:resumed:dry-run",
        )

    # Apply fill with OCC (reservation optional for buys).
    reserve_amt = risk.notional_usd or _ZERO
    if sized.side == "sell":
        reserve_amt = _ZERO
    if reserve_amt > 0:
        shadow.reserve_cash(
            intent_id=intent_id,
            amount=reserve_amt,
            expected_version=before["version"],
            cycle_key=intent["cycle_key"],
        )
        before = shadow.snapshot()

    after, fill_meta = _simulate_fill(before, sized.side, sized.quantity, open_price, costs)
    after["reserved_cash_usd"] = _ZERO
    evidence["fill"] = fill_meta
    outbox = {
        "kind": "risk_evaluation",
        "payload": {
            "proposal_id": proposal.id,
            "source": "shadow_pending_resume",
            "symbol": SYMBOL,
            "side": sized.side,
            "quantity": str(sized.quantity),
            "verdict": risk.verdict,
            "reasons": risk.reasons,
            "policy_version": risk.policy_version,
            "policy_hash": risk.policy_hash,
            "notional_usd": None if risk.notional_usd is None else str(risk.notional_usd),
            "proposal_as_of": observation_as_of.isoformat(),
            "evaluated_at": now.isoformat(),
            "cycle_key": intent["cycle_key"],
        },
    }
    return _finish(
        shadow,
        mode=mode,
        label=label,
        before=before,
        after=after,
        status="filled",
        intent=sized.side,
        warnings=[sized.reason] if sized.is_partial else [],
        evidence=evidence,
        duration_ms=0,
        mutate=True,
        signal_session=signal_day,
        fill_session=fill_day,
        target_weight=target,
        proposal_id=proposal.id,
        risk_verdict=risk.verdict,
        risk_reasons=risk.reasons,
        fill_price=open_price,
        fill_qty=sized.quantity,
        fill_side=sized.side,
        costs_usd=Decimal(fill_meta["costs_usd"]),
        record_equity=True,
        mark_price=open_price,
        cycle_key=intent["cycle_key"],
        expected_version=before["version"],
        commit_reservation_intent_id=intent_id if reserve_amt > 0 else None,
        outbox=outbox,
    )
