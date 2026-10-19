"""Run one isolated lab session from the existing shadow and risk components.

Historical replay reads stored SIP bars and lets spy_tsmom_12_1 decide.
Synthetic scenarios use an explicit price fixture. Neither path opens the
forward shadow database or submits a broker order.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.finance.accounting import (
    ACCOUNTING_CONVENTION,
    Book,
    economic_identity,
    mark_equity,
    mark_sessions,
    max_drawdown,
    unrealized_pnl,
)
from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore, StoredBar, content_hash
from nomadquant.research.models import CostModel
from nomadquant.risk import InternalLedger, PriceQuote, Proposal, RiskEngine, RiskPolicy
from nomadquant.shadow.cycle import LABEL_RETRO, LOOKBACK, SKIP, run_shadow_cycle
from nomadquant.shadow.store import ShadowStore, shadow_path_for_label
from nomadquant.shadow.verify import verify_cycle

SCENARIOS = (
    "replay_3m",
    "replay_12m",
    "replay_3y",
    "replay_full",
    "mechanics",
    "crash_stress",
    "observed_quote",
)
_WINDOWS = {"replay_3m": 92, "replay_12m": 366, "replay_3y": 366 * 3}
_HISTORICAL = "HISTORICAL SIMULATION"
_SYNTHETIC = "SYNTHETIC MECHANICS TEST"
_QUOTE = "OBSERVED QUOTE READINESS"
_TOKEN = re.compile(r"[?&]token=([^&\s]+)")


def run_lab(settings: Settings, scenario: str) -> dict[str, Any]:
    """Create a new isolated session. The forward ledger path is never opened."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r}.")
    forward = Path(settings.shadow_path)
    before = _fingerprint(forward)
    session_id = uuid.uuid4().hex[:12]
    root = forward.parent / "lab" / session_id
    root.mkdir(parents=True, exist_ok=True)
    if scenario in _WINDOWS or scenario == "replay_full":
        payload = _historical(settings, root, scenario)
    elif scenario == "observed_quote":
        payload = _quotes(settings, root)
    else:
        payload = _mechanics(root, interrupt=scenario == "crash_stress")
    payload["id"] = session_id
    payload["scenario"] = scenario
    payload["created_at"] = datetime.now(UTC).isoformat()
    payload["broker_orders"] = False
    payload["forward_ledger_touched"] = _fingerprint(forward) != before
    payload["isolated_root"] = root.name
    if payload["forward_ledger_touched"]:
        raise RuntimeError("Simulation lab touched the forward shadow ledger.")
    _write(forward.parent / "lab", session_id, payload)
    return _public(payload)


def latest_session(settings: Settings) -> dict[str, Any] | None:
    pointer = Path(settings.shadow_path).parent / "lab" / "latest.json"
    if not pointer.is_file():
        return None
    try:
        body = json.loads(pointer.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    session_id = str(body.get("id") or "")
    path = pointer.parent / session_id / "session.json"
    if not path.is_file():
        return None
    try:
        return _public(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return None


def _historical(settings: Settings, root: Path, scenario: str) -> dict[str, Any]:
    market = MarketStore.open_readonly(settings.market_data_path)
    if market is None:
        return _empty(_HISTORICAL, "No local market database is available.")
    sessions = sorted(market.sessions("SPY", "sip"))
    if not sessions:
        return _empty(_HISTORICAL, "No SPY SIP sessions are stored.")
    end = sessions[-1]
    if scenario == "replay_full":
        window = sessions
    else:
        cut = end - timedelta(days=_WINDOWS[scenario])
        window = [item for item in sessions if item >= cut]
    if not window:
        return _empty(_HISTORICAL, "The selected window has no stored sessions.")
    starts = [item for item in _month_starts(window) if sessions.index(item) >= LOOKBACK + SKIP + 1]
    shadow = root / "shadow.sqlite"
    risk = root / "risk.sqlite"
    isolated_market = _replay_market(settings.market_data_path, root / "market.sqlite")
    events: list[dict[str, Any]] = []
    closes = {row[0]: row[4] for row in market.session_ohlc("SPY", "sip", sessions[0], end)}
    for signal in starts:
        nxt = next((item for item in sessions if item > signal), None)
        clock = modeled_available_at(nxt or signal) + timedelta(minutes=1)
        result = run_shadow_cycle(
            market_path=isolated_market,
            shadow_path=shadow,
            risk_path=risk,
            mode="apply",
            as_of=clock,
            signal_session=signal,
            label=LABEL_RETRO,
            context="HISTORICAL_SIMULATION",
        )
        events.append(_event(result, _HISTORICAL, closes))
    duplicate = _duplicate(shadow, risk, isolated_market, events, sessions)
    if duplicate is not None:
        duplicate["label"] = _HISTORICAL
        events.append(duplicate)
    bars = [
        {"session": item.isoformat(), "close": str(closes[item])}
        for item in window
        if item in closes
    ]
    summary = _summary(
        events,
        _HISTORICAL,
        bars,
        _curve(_span(sessions, window[0], window[-1], events), closes, events),
    )
    summary["verification"] = _verify(shadow, risk, isolated_market, events)
    summary["approval"] = _approval_drill(root / "approval")
    summary["limitations"] = (
        "Price-only SIP daily bars. Dividends are not in this result. "
        "The isolated copy uses each bar's modeled 16:30 New York availability "
        "as its retrieval time, because this computer downloaded the history later. "
        "This is a historical replay, not forward profit."
    )
    summary["bars"] = bars[:: max(1, len(bars) // 400)]
    return summary


def _mechanics(root: Path, *, interrupt: bool) -> dict[str, Any]:
    sessions = sessions_between(date(2018, 1, 2), date(2019, 9, 1))
    market_path = root / "market.sqlite"
    _write_synthetic(market_path, sessions)
    shadow = root / "shadow.sqlite"
    risk = root / "risk.sqlite"
    closes = {item: _synthetic_price(index) for index, item in enumerate(sessions)}
    starts = [
        item for item in _month_starts(sessions) if sessions.index(item) >= LOOKBACK + SKIP + 1
    ]
    events: list[dict[str, Any]] = []
    buy_day = _first_signal(closes, sessions, starts, positive=True)
    sell_day = _first_signal(closes, sessions, starts, positive=False, after=buy_day)
    hold_day = next(item for item in sessions if buy_day < item < sell_day and item not in starts)
    for signal in (buy_day, hold_day, sell_day):
        nxt = next(item for item in sessions if item > signal)
        result = run_shadow_cycle(
            market_path=market_path,
            shadow_path=shadow,
            risk_path=risk,
            mode="apply",
            as_of=datetime(nxt.year, nxt.month, nxt.day, 22, tzinfo=UTC),
            signal_session=signal,
            label=LABEL_RETRO,
            context="SYNTHETIC_MECHANICS_TEST",
        )
        events.append(_event(result, _SYNTHETIC, closes))
    events.append(_duplicate_apply(market_path, shadow, risk, buy_day, sessions, closes))
    events.append(_risk_rejection())
    if interrupt:
        events.append(_interrupt(shadow))
    summary = _summary(
        events, _SYNTHETIC, [], _curve(_span(sessions, buy_day, sell_day, events), closes, events)
    )
    summary["verification"] = _verify(shadow, risk, market_path, events)
    summary["approval"] = _approval_drill(root / "approval")
    summary["bars"] = [
        {"session": item.isoformat(), "close": str(closes[item])}
        for item in sessions
        if buy_day <= item <= sell_day
    ]
    summary["limitations"] = (
        "Synthetic prices created for the mechanics fixture. "
        "They are not market history and not forward profit."
    )
    return summary


def _quotes(settings: Settings, root: Path) -> dict[str, Any]:
    from nomadquant.shadow.observed_quote import QuoteObservation, simulate_observed_fill

    now = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)
    costs = CostModel(
        commission_usd=Decimal("0"),
        spread_bps=Decimal("1"),
        slippage_bps=Decimal("1"),
        min_notional_usd=Decimal("1"),
        quantity_precision=6,
    )
    cases: list[tuple[str, QuoteObservation | None, bool, datetime]] = [
        ("missing", None, True, now),
        (
            "retrieved_after_decision",
            _sample(now - timedelta(minutes=2), now + timedelta(seconds=1)),
            True,
            now,
        ),
        ("stale", _sample(now - timedelta(minutes=10), now - timedelta(minutes=10)), True, now),
        ("crossed", _sample(now, now, bid=Decimal("101"), ask=Decimal("100")), True, now),
        ("closed_market", _sample(now - timedelta(seconds=5), now), False, now),
        ("fresh_open", _sample(now - timedelta(seconds=5), now - timedelta(seconds=1)), True, now),
    ]
    events = []
    for name, quote, market_open, decision_time in cases:
        result = simulate_observed_fill(
            quote,
            side="buy",
            decision_time=decision_time,
            market_open=market_open,
            cash=Decimal("100"),
            held_quantity=Decimal("0"),
            costs=costs,
            policy=RiskPolicy(),
        )
        events.append(
            {
                "label": _QUOTE,
                "session": decision_time.date().isoformat(),
                "decision": name,
                "status": result["status"],
                "risk_verdict": None,
                "risk_reasons": [result["reason"]],
                "side": None,
                "quantity": result["quantity"],
                "price": result.get("observed_price"),
                "costs_usd": None,
                "cash_usd": "100",
                "holdings": {},
                "equity_usd": "100",
                "realized_pnl_usd": "0",
                "momentum": None,
                "close": None,
                "authoritative": False,
                "note": result["reason"],
            }
        )
    fresh = next(item for item in events if item["decision"] == "fresh_open")
    insufficient = simulate_observed_fill(
        _sample(now - timedelta(seconds=5), now - timedelta(seconds=1)),
        side="buy",
        decision_time=now,
        market_open=True,
        cash=Decimal("1"),
        held_quantity=Decimal("0"),
        costs=costs,
        policy=RiskPolicy(),
    )
    events.append(
        {
            **fresh,
            "decision": "insufficient_cash",
            "status": insufficient["status"],
            "note": insufficient["reason"],
            "risk_reasons": [insufficient["reason"]],
            "quantity": insufficient["quantity"],
        }
    )
    live = _live_quote(settings)
    summary = _summary(events, _QUOTE, [])
    summary["live_quote"] = live
    summary["strategy_signal_created"] = False
    summary["ledger_mutated"] = False
    summary["approval"] = {"status": "not_applicable", "requests": []}
    summary["verification"] = {"checked": 0, "passed": 0, "results": []}
    summary["limitations"] = (
        "Quote cases are readiness checks. They do not create a strategy signal "
        "and they do not write the forward ledger."
    )
    summary["isolated_note"] = root.name
    return summary


def _approval_drill(root: Path) -> dict[str, Any]:
    """Compose, approve, reject, and expire in an outbox that is not the user's."""
    from nomadquant.approvals.service import create_approval_request, decide_approval_request

    root.mkdir(parents=True, exist_ok=True)
    isolated = Settings(
        shadow_path=str(root / "unused-shadow.sqlite"),
        market_data_path=str(root / "unused-market.sqlite"),
        risk_path=str(root / "unused-risk.sqlite"),
        approval_path=str(root / "approvals.sqlite"),
        approval_outbox_dir=str(root / "outbox"),
        smtp_host="",
        approval_email_to="",
    )
    clock = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
    created = []
    for action in ("BUY", "SELL", "BUY"):
        created.append(
            create_approval_request(
                isolated,
                instrument="SPY",
                action=action,
                quantity="0.05",
                notional_usd="40",
                why=f"Isolated lab proposal to {action} SPY inside the $100 fixture.",
                risk_summary="Sized under the $50 single-trade cap and the $5 cash reserve.",
                caveats="Synthetic mechanics approval. Not a forward fill and not an Alpaca order.",
                now=clock,
                preview_hash="",
            )
        )
    buy, sell, expiring = created
    buy_token = _token_from_outbox(isolated, str(buy["id"]))
    sell_token = _token_from_outbox(isolated, str(sell["id"]))
    expire_token = _token_from_outbox(isolated, str(expiring["id"]))
    approved = decide_approval_request(
        isolated,
        str(buy["id"]),
        token=buy_token,
        action="approve",
        confirm="1",
        now=clock,
    )
    rejected = decide_approval_request(
        isolated,
        str(sell["id"]),
        token=sell_token,
        action="reject",
        confirm="1",
        now=clock,
    )
    expired = decide_approval_request(
        isolated,
        str(expiring["id"]),
        token=expire_token,
        action="approve",
        confirm="1",
        now=clock + timedelta(hours=2),
    )
    reused = False
    try:
        decide_approval_request(
            isolated,
            str(buy["id"]),
            token=buy_token,
            action="approve",
            confirm="1",
            now=clock,
        )
    except ValueError:
        reused = True
    return {
        "status": "completed",
        "delivery": "local_outbox",
        "smtp_used": False,
        "requests": [
            {
                "action": "BUY",
                "result": approved.get("status"),
                "fill_authorized": False,
                "note": "Email approval alone does not authorize a simulated fill.",
            },
            {"action": "SELL", "result": rejected.get("status"), "fill_authorized": False},
            {"action": "BUY", "result": expired.get("status"), "fill_authorized": False},
        ],
        "token_reuse_blocked": reused,
        "broker_orders": False,
    }


def _event(result: dict[str, Any], label: str, closes: dict[date, Decimal]) -> dict[str, Any]:
    after_raw = result.get("ledger_after")
    after: dict[str, Any] = after_raw if isinstance(after_raw, dict) else {}
    holdings_raw = after.get("holdings")
    holdings: dict[str, Any] = holdings_raw if isinstance(holdings_raw, dict) else {}
    basis_raw = after.get("cost_basis")
    basis: dict[str, Any] = basis_raw if isinstance(basis_raw, dict) else {}
    cash = Decimal(str(after.get("cash_usd") or "100"))
    realized = Decimal(str(after.get("realized_pnl_usd") or "0"))
    status = str(result.get("status") or "")
    signal = _parse_day(result.get("signal_session"))
    fill = _parse_day(result.get("fill_session"))
    # A fill is valued at the fill session's close, after the open execution.
    # The signal close is only a valid mark when the book has not yet been filled.
    mark_day = fill if status == "filled" and fill is not None else signal
    close = None if mark_day is None else closes.get(mark_day)
    book = _book(cash, holdings, basis, realized)
    held = any(qty != 0 for qty in book.holdings.values())
    if held and (close is None or close <= 0):
        equity: Decimal | None = None
        unrealized: Decimal | None = None
        valuation = "UNAVAILABLE"
    else:
        marks = {} if close is None else {"SPY": close}
        equity = mark_equity(book, marks)
        unrealized = unrealized_pnl(book, marks)
        valuation = "ok" if equity is not None else "UNAVAILABLE"
    return {
        "label": label,
        "session": None if mark_day is None else mark_day.isoformat(),
        "signal_session": None if signal is None else signal.isoformat(),
        "fill_session": None if fill is None else fill.isoformat(),
        "decision": result.get("intent") or result.get("status"),
        "status": status,
        "risk_verdict": result.get("risk_verdict"),
        "risk_reasons": list(result.get("risk_reasons") or []),
        "side": result.get("fill_side"),
        "quantity": result.get("fill_qty"),
        "price": result.get("fill_price"),
        "costs_usd": result.get("costs_usd"),
        "cash_usd": str(cash),
        "holdings": {key: str(value) for key, value in holdings.items()},
        "cost_basis": {key: str(value) for key, value in basis.items()},
        "equity_usd": "UNAVAILABLE" if equity is None else str(equity),
        "unrealized_pnl_usd": None if unrealized is None else str(unrealized),
        "realized_pnl_usd": str(realized),
        "realized_increment_usd": None,
        "valuation_status": valuation,
        "valuation_session": None if mark_day is None else mark_day.isoformat(),
        "valuation_price": None if close is None else str(close),
        "valuation_as_of": None if mark_day is None else modeled_available_at(mark_day).isoformat(),
        "authoritative": status in {"filled", "no_trade"},
        "momentum": result.get("momentum"),
        "close": None if close is None else str(close),
        "cycle_id": result.get("id"),
        "note": "",
    }


def _summary(
    events: list[dict[str, Any]],
    label: str,
    bars: list[dict[str, str]],
    curve: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _assign_realized_increments(events)
    financial = [item for item in events if item.get("authoritative")]
    state = financial[-1] if financial else None
    marked = [item for item in (curve or []) if item.get("status") == "ok"]
    ending_point = marked[-1] if marked else None
    if ending_point is not None and ending_point.get("equity") is not None:
        ending: Decimal | None = Decimal(str(ending_point["equity"]))
        ending_text = str(ending)
        cash_text = str(ending_point["cash"])
        unrealized_text = str(ending_point["unrealized"])
        realized = Decimal(str(ending_point["realized"]))
    elif state is not None and state.get("valuation_status") == "ok":
        ending = Decimal(str(state["equity_usd"]))
        ending_text = str(ending)
        cash_text = str(state["cash_usd"])
        unrealized_text = str(state.get("unrealized_pnl_usd") or "0")
        realized = Decimal(str(state["realized_pnl_usd"]))
    elif state is not None:
        ending = None
        ending_text = "UNAVAILABLE"
        cash_text = str(state["cash_usd"])
        unrealized_text = "UNAVAILABLE"
        realized = Decimal(str(state["realized_pnl_usd"]))
    else:
        ending = Decimal("100")
        ending_text = "100"
        cash_text = "100"
        unrealized_text = "0"
        realized = Decimal("0")
    drawdown = max_drawdown(
        [None if item.get("equity") is None else Decimal(str(item["equity"])) for item in curve]
        if curve
        else [
            None if item.get("valuation_status") != "ok" else Decimal(str(item["equity_usd"]))
            for item in financial
        ]
    )
    buys = sum(1 for item in events if item.get("side") == "buy" and item.get("status") == "filled")
    sells = sum(
        1 for item in events if item.get("side") == "sell" and item.get("status") == "filled"
    )
    wins, losses = _win_loss(events)
    costs = sum(
        (Decimal(str(item.get("costs_usd") or "0")) for item in financial),
        Decimal("0"),
    )
    first_close = Decimal(bars[0]["close"]) if bars else None
    last_close = Decimal(bars[-1]["close"]) if bars else None
    spy = None
    if first_close and last_close and first_close > 0:
        spy = str((Decimal("100") * last_close / first_close).quantize(Decimal("0.01")))
    holdings = {} if state is None else state.get("holdings") or {}
    identity = _identity(state, ending_point)
    exposure = "UNAVAILABLE"
    if ending is not None:
        exposure = str(max(Decimal("0"), ending - Decimal(cash_text)))
    return {
        "label": label,
        "starting_usd": "100",
        "ending_usd": ending_text,
        "cash_usd": cash_text,
        "holdings": holdings,
        "buys": buys,
        "sells": sells,
        "wins": wins,
        "losses": losses,
        "realized_pnl_usd": str(realized),
        "unrealized_pnl_usd": unrealized_text,
        "costs_usd": str(costs),
        "max_drawdown": (
            "UNAVAILABLE" if drawdown is None else str(drawdown.quantize(Decimal("0.0001")))
        ),
        "exposure_usd": exposure,
        "pnl_convention": ACCOUNTING_CONVENTION,
        "reconciliation": identity,
        "equity_curve": [
            {
                "session": item["session"],
                "equity": None if item.get("equity") is None else str(item["equity"]),
                "status": item["status"],
            }
            for item in (curve or [])
        ],
        "comparisons": {
            "cash": "100",
            "spy_buy_hold_price_only": spy,
            "note": "SPY buy-and-hold uses raw closes in this window. It is not total return.",
        },
        "events": events,
        "forward_profit": False,
    }


def _verify(
    shadow: Path, risk: Path, market: str | Path, events: list[dict[str, Any]]
) -> dict[str, Any]:
    ledger = shadow_path_for_label(shadow, LABEL_RETRO)
    isolated = Settings(
        shadow_path=str(ledger),
        risk_path=str(risk),
        market_data_path=str(market),
    )
    results = []
    for item in events:
        cycle_id = item.get("cycle_id")
        if not isinstance(cycle_id, int):
            continue
        if item.get("status") not in {"filled", "no_trade"}:
            continue
        report = verify_cycle(isolated, cycle_id)
        results.append({"cycle_id": cycle_id, "status": report.get("status")})
    return {
        "checked": len(results),
        "passed": sum(1 for item in results if item["status"] == "PASS"),
        "results": results[:12],
    }


def _duplicate(
    shadow: Path,
    risk: Path,
    market: str | Path,
    events: list[dict[str, Any]],
    sessions: list[date],
) -> dict[str, Any] | None:
    filled = next((item for item in events if item.get("status") == "filled"), None)
    if filled is None:
        return None
    raw_signal = filled.get("signal_session") or filled.get("session")
    if not raw_signal:
        return None
    signal = date.fromisoformat(str(raw_signal))
    event = _duplicate_apply(market, shadow, risk, signal, sessions, {})
    latest = events[-1]
    event["status"] = "duplicate_prevented"
    event["cash_usd"] = latest["cash_usd"]
    event["holdings"] = latest["holdings"]
    event["equity_usd"] = latest["equity_usd"]
    event["realized_pnl_usd"] = latest["realized_pnl_usd"]
    event["close"] = latest["close"]
    return event


def _duplicate_apply(
    market: str | Path,
    shadow: Path,
    risk: Path,
    signal: date,
    sessions: list[date],
    closes: dict[date, Decimal],
) -> dict[str, Any]:
    nxt = next(item for item in sessions if item > signal)
    again = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow,
        risk_path=risk,
        mode="apply",
        as_of=datetime(nxt.year, nxt.month, nxt.day, 22, tzinfo=UTC),
        signal_session=signal,
        label=LABEL_RETRO,
        context="DUPLICATE_PREVENTION",
    )
    event = _event(again, _SYNTHETIC, closes)
    event["decision"] = "duplicate_prevented"
    event["status"] = "duplicate_prevented"
    event["authoritative"] = False
    event["note"] = "The same cycle key returned the original row."
    event["side"] = None
    return event


def _interrupt(shadow: Path) -> dict[str, Any]:
    ledger = shadow_path_for_label(shadow, LABEL_RETRO)
    store = ShadowStore(ledger, namespace="retrospective")
    before = store.snapshot()
    store.reserve_cash(
        intent_id="lab:interrupted",
        amount=Decimal("1"),
        expected_version=int(before["version"]),
        cycle_key="lab:interrupted",
    )
    recovered = store.recover_interrupted()
    after = store.snapshot()
    return {
        "label": _SYNTHETIC,
        "session": None,
        "decision": "recovery",
        "status": "recovered",
        "risk_verdict": "PASS",
        "risk_reasons": [],
        "side": None,
        "quantity": None,
        "price": None,
        "costs_usd": "0",
        "cash_usd": str(after["cash_usd"]),
        "holdings": {key: str(value) for key, value in after["holdings"].items()},
        "equity_usd": str(after["cash_usd"]),
        "realized_pnl_usd": str(after["realized_pnl_usd"]),
        "authoritative": False,
        "momentum": None,
        "close": None,
        "cycle_id": None,
        "note": f"Released {recovered.get('released_intent_ids')}.",
    }


def _risk_rejection() -> dict[str, Any]:
    now = datetime(2026, 10, 19, 15, tzinfo=UTC)
    proposal = Proposal(
        id="lab-oversized",
        source="simulation_lab",
        symbol="SPY",
        side="buy",
        quantity=Decimal("2"),
        limit_price=Decimal("100"),
        as_of=now,
    )
    result = RiskEngine(RiskPolicy()).evaluate(
        proposal,
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": PriceQuote(price=Decimal("100"), as_of=now, feed="sip")},
        now=now,
        clock="historical",
    )
    return {
        "label": _SYNTHETIC,
        "session": "2026-10-19",
        "decision": "risk_rejected",
        "status": "risk_rejected",
        "risk_verdict": result.verdict,
        "risk_reasons": list(result.reasons),
        "side": None,
        "quantity": "0",
        "price": None,
        "costs_usd": "0",
        "cash_usd": "100",
        "holdings": {},
        "equity_usd": "100",
        "realized_pnl_usd": "0",
        "authoritative": False,
        "momentum": None,
        "close": "100",
        "cycle_id": None,
        "note": "A $200 order cannot be paid from the $100 book.",
    }


def _live_quote(settings: Settings) -> dict[str, Any]:
    if not settings.credentials_configured:
        return {"status": "NOT_RUN", "reason": "credentials_absent", "ledger_mutated": False}
    try:
        from nomadquant.marketdata.live_quote import live_quotes
        from nomadquant.overview import market_clock
        from nomadquant.shadow.observed_quote import QuoteObservation, simulate_observed_fill

        payload = live_quotes(settings)
        spy = (payload.get("quotes") or {}).get("SPY") or {}
        retrieved = _aware(str(payload.get("retrieved_at") or ""))
        traded = _aware(str(spy.get("quote_time") or ""))
        if spy.get("bid") is None or spy.get("ask") is None or retrieved is None or traded is None:
            return {
                "status": "UNAVAILABLE",
                "reason": "bid_or_ask_missing",
                "ledger_mutated": False,
            }
        quote = QuoteObservation(
            symbol="SPY",
            feed="iex",
            bid=Decimal(str(spy["bid"])),
            ask=Decimal(str(spy["ask"])),
            market_timestamp=traded,
            retrieved_at=retrieved,
            source="alpaca_snapshot_latest_quote",
        )
        earlier = simulate_observed_fill(
            quote,
            side="buy",
            decision_time=min(retrieved, traded) - timedelta(seconds=5),
            market_open=True,
            cash=Decimal("100"),
            held_quantity=Decimal("0"),
            costs=CostModel(),
        )
        clock = market_clock(datetime.now(UTC))
        current = simulate_observed_fill(
            quote,
            side="buy",
            decision_time=max(retrieved, traded),
            market_open=clock.get("state") == "open",
            cash=Decimal("100"),
            held_quantity=Decimal("0"),
            costs=CostModel(),
        )
        return {
            "status": "observed",
            "market_state": clock.get("state"),
            "bid": str(quote.bid),
            "ask": str(quote.ask),
            "market_timestamp": quote.market_timestamp.isoformat(),
            "retrieved_at": quote.retrieved_at.isoformat(),
            "earlier_decision": earlier["reason"],
            "same_time_decision": current["status"],
            "same_time_reason": current["reason"],
            "strategy_signal_created": False,
            "ledger_mutated": False,
        }
    except Exception as exc:  # noqa: BLE001 - readiness must report the failure kind
        return {"status": "UNAVAILABLE", "reason": type(exc).__name__, "ledger_mutated": False}


def _sample(
    market_timestamp: datetime,
    retrieved_at: datetime,
    *,
    bid: Decimal = Decimal("100"),
    ask: Decimal = Decimal("100.02"),
) -> Any:
    from nomadquant.shadow.observed_quote import QuoteObservation

    return QuoteObservation(
        symbol="SPY",
        feed="iex",
        bid=bid,
        ask=ask,
        market_timestamp=market_timestamp,
        retrieved_at=retrieved_at,
        source="lab_fixture",
    )


def _replay_market(source: str, dest: Path) -> Path:
    """Copy stored bars into the lab and stamp retrieval at modeled availability."""
    origin = MarketStore.open_readonly(source)
    if origin is None:
        return dest
    rows = origin.bars(
        ["SPY"],
        "sip",
        datetime(1990, 1, 1, tzinfo=UTC),
        datetime(2100, 1, 1, tzinfo=UTC),
        datetime(2100, 1, 1, tzinfo=UTC),
    )
    cloned = [replace(bar, first_retrieved_at=bar.available_at) for bar in rows]
    if cloned:
        MarketStore(dest).write_bars(cloned)
    return dest


def _write_synthetic(path: Path, sessions: list[date]) -> None:
    store = MarketStore(path)
    bars: list[StoredBar] = []
    for index, session in enumerate(sessions):
        close = _synthetic_price(index)
        raw = StoredBar(
            symbol="SPY",
            session_date=session,
            timestamp=datetime(session.year, session.month, session.day, 14, 30, tzinfo=UTC),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=Decimal("1000"),
            provider="alpaca",
            feed="sip",
            adjustment="raw",
            timeframe="1Day",
            currency="USD",
            available_at=datetime(session.year, session.month, session.day, 21, 30, tzinfo=UTC),
            first_retrieved_at=datetime(session.year, session.month, session.day, 21, tzinfo=UTC),
            content_hash="pending",
        )
        bars.append(StoredBar(**{**raw.__dict__, "content_hash": content_hash(raw)}))
    store.write_bars(bars)


def _synthetic_price(index: int) -> Decimal:
    if index < 180:
        return Decimal("100")
    if index < 260:
        return Decimal("100") + Decimal(index - 180) * Decimal("0.5")
    fallen = Decimal("140") - Decimal(index - 260) * Decimal("0.35")
    return fallen if fallen > Decimal("20") else Decimal("20")


def _first_signal(
    closes: dict[date, Decimal],
    sessions: list[date],
    starts: list[date],
    *,
    positive: bool,
    after: date | None = None,
) -> date:
    from nomadquant.research.signals import momentum_return

    for session in starts:
        if after is not None and session <= after:
            continue
        value = momentum_return(closes, sessions, session, LOOKBACK, SKIP) or Decimal("0")
        if positive and value > 0:
            return session
        if not positive and value < 0:
            return session
    raise RuntimeError("Synthetic fixture did not produce the expected signal.")


def _month_starts(sessions: list[date]) -> list[date]:
    starts: list[date] = []
    for session in sessions:
        prior = [item for item in sessions if item < session]
        if not prior or prior[-1].month != session.month:
            starts.append(session)
    return starts


def _token_from_outbox(settings: Settings, request_id: str) -> str:
    text = Path(settings.approval_outbox_dir, f"{request_id}.txt").read_text(encoding="utf-8")
    match = _TOKEN.search(text)
    if match is None:
        raise RuntimeError("The local approval outbox did not contain a review token.")
    return match.group(1)


def _aware(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _fingerprint(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _span(sessions: list[date], start: date, end: date, events: list[dict[str, Any]]) -> list[date]:
    last = end
    for item in events:
        day = _parse_day(item.get("fill_session"))
        if item.get("authoritative") and day is not None and day > last:
            last = day
    return [item for item in sessions if start <= item <= last]


def _curve(
    sessions: list[date], closes: dict[date, Decimal], events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    snapshots: list[tuple[date, Book]] = []
    for item in events:
        if not item.get("authoritative") or item.get("status") != "filled":
            continue
        day = _parse_day(item.get("fill_session"))
        if day is None:
            continue
        snapshots.append((day, _book_from_event(item)))
    return mark_sessions(sessions, closes, snapshots)


def _book(
    cash: Decimal,
    holdings: dict[str, Any],
    basis: dict[str, Any],
    realized: Decimal,
) -> Book:
    return Book(
        cash=cash,
        holdings={str(key): Decimal(str(value)) for key, value in holdings.items()},
        cost_basis={str(key): Decimal(str(value)) for key, value in basis.items()},
        realized_pnl=realized,
    )


def _book_from_event(item: dict[str, Any]) -> Book:
    raw_holdings = item.get("holdings")
    raw_basis = item.get("cost_basis")
    holdings: dict[str, Any] = raw_holdings if isinstance(raw_holdings, dict) else {}
    basis: dict[str, Any] = raw_basis if isinstance(raw_basis, dict) else {}
    return _book(
        Decimal(str(item.get("cash_usd") or "0")),
        holdings,
        basis,
        Decimal(str(item.get("realized_pnl_usd") or "0")),
    )


def _assign_realized_increments(events: list[dict[str, Any]]) -> None:
    previous = Decimal("0")
    for item in events:
        if not item.get("authoritative"):
            item["realized_increment_usd"] = None
            continue
        total = Decimal(str(item.get("realized_pnl_usd") or "0"))
        if item.get("side") == "sell" and item.get("status") == "filled":
            item["realized_increment_usd"] = str(total - previous)
        else:
            item["realized_increment_usd"] = "0"
        previous = total


def _win_loss(events: list[dict[str, Any]]) -> tuple[int, int]:
    increments = [
        Decimal(str(item["realized_increment_usd"]))
        for item in events
        if item.get("side") == "sell"
        and item.get("status") == "filled"
        and item.get("realized_increment_usd") not in {None, ""}
    ]
    wins = sum(1 for item in increments if item > 0)
    losses = sum(1 for item in increments if item < 0)
    return wins, losses


def _identity(state: dict[str, Any] | None, ending_point: dict[str, Any] | None) -> dict[str, Any]:
    if ending_point is None or ending_point.get("status") != "ok" or state is None:
        if state is None:
            return {"status": "PASS", "residual": "0", "convention": ACCOUNTING_CONVENTION}
        return {"status": "UNAVAILABLE", "residual": None, "convention": ACCOUNTING_CONVENTION}
    close = ending_point.get("close")
    book = _book_from_event(state)
    marks = {} if close is None else {"SPY": Decimal(str(close))}
    if any(qty != 0 for qty in book.holdings.values()) and not marks:
        return {"status": "UNAVAILABLE", "residual": None, "convention": ACCOUNTING_CONVENTION}
    checked = economic_identity(book, marks, starting=Decimal("100"))
    return {
        "status": checked["status"],
        "residual": None if checked["residual"] is None else str(checked["residual"]),
        "convention": ACCOUNTING_CONVENTION,
    }


def _parse_day(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _empty(label: str, reason: str) -> dict[str, Any]:
    summary = _summary([], label, [])
    summary["limitations"] = reason
    summary["approval"] = {"status": "not_run", "requests": []}
    summary["verification"] = {"checked": 0, "passed": 0, "results": []}
    summary["bars"] = []
    return summary


def _write(lab_root: Path, session_id: str, payload: dict[str, Any]) -> None:
    path = lab_root / session_id / "session.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (lab_root / "latest.json").write_text(
        json.dumps({"id": session_id, "label": payload.get("label")}),
        encoding="utf-8",
    )


def _public(payload: dict[str, Any]) -> dict[str, Any]:
    hidden = {"isolated_root"}
    return {key: value for key, value in payload.items() if key not in hidden}
