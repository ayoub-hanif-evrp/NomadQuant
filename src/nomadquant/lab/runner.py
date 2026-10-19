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
        events.append(_event(result, _HISTORICAL, closes.get(signal)))
    duplicate = _duplicate(shadow, risk, isolated_market, events, sessions)
    if duplicate is not None:
        duplicate["label"] = _HISTORICAL
        events.append(duplicate)
    bars = [
        {"session": item.isoformat(), "close": str(closes[item])}
        for item in window
        if item in closes
    ]
    summary = _summary(events, _HISTORICAL, bars)
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
        events.append(_event(result, _SYNTHETIC, closes[signal]))
    events.append(_duplicate_apply(market_path, shadow, risk, buy_day, sessions, closes))
    events.append(_risk_rejection())
    if interrupt:
        events.append(_interrupt(shadow))
    summary = _summary(events, _SYNTHETIC, [])
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
        ("stale", _sample(now - timedelta(hours=2), now - timedelta(hours=2)), True, now),
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
            {"action": "BUY", "result": approved.get("status"), "fill_authorized": True},
            {"action": "SELL", "result": rejected.get("status"), "fill_authorized": False},
            {"action": "BUY", "result": expired.get("status"), "fill_authorized": False},
        ],
        "token_reuse_blocked": reused,
        "broker_orders": False,
    }


def _event(result: dict[str, Any], label: str, close: Decimal | None) -> dict[str, Any]:
    after_raw = result.get("ledger_after")
    after: dict[str, Any] = after_raw if isinstance(after_raw, dict) else {}
    holdings_raw = after.get("holdings")
    holdings: dict[str, Any] = holdings_raw if isinstance(holdings_raw, dict) else {}
    cash = Decimal(str(after.get("cash_usd") or "100"))
    marked = close or Decimal("0")
    held = Decimal(str(holdings.get("SPY") or "0"))
    equity = cash + held * marked if marked else cash
    return {
        "label": label,
        "session": result.get("signal_session"),
        "decision": result.get("intent") or result.get("status"),
        "status": result.get("status"),
        "risk_verdict": result.get("risk_verdict"),
        "risk_reasons": list(result.get("risk_reasons") or []),
        "side": result.get("fill_side"),
        "quantity": result.get("fill_qty"),
        "price": result.get("fill_price"),
        "costs_usd": result.get("costs_usd"),
        "cash_usd": str(cash),
        "holdings": {key: str(value) for key, value in holdings.items()},
        "equity_usd": str(equity),
        "realized_pnl_usd": str(after.get("realized_pnl_usd") or "0"),
        "momentum": result.get("momentum"),
        "close": None if close is None else str(close),
        "cycle_id": result.get("id"),
        "note": "",
    }


def _summary(
    events: list[dict[str, Any]], label: str, bars: list[dict[str, str]]
) -> dict[str, Any]:
    equities = [Decimal(item["equity_usd"]) for item in events] or [Decimal("100")]
    peak = Decimal("100")
    drawdown = Decimal("0")
    for value in equities:
        peak = max(peak, value)
        if peak:
            drawdown = max(drawdown, (peak - value) / peak)
    buys = sum(1 for item in events if item.get("side") == "buy" and item.get("status") == "filled")
    sells = sum(
        1 for item in events if item.get("side") == "sell" and item.get("status") == "filled"
    )
    ending = equities[-1]
    costs = sum(Decimal(str(item.get("costs_usd") or "0")) for item in events)
    realized = Decimal(str(events[-1]["realized_pnl_usd"])) if events else Decimal("0")
    first_close = Decimal(bars[0]["close"]) if bars else None
    last_close = Decimal(bars[-1]["close"]) if bars else None
    spy = None
    if first_close and last_close and first_close > 0:
        spy = str((Decimal("100") * last_close / first_close).quantize(Decimal("0.01")))
    return {
        "label": label,
        "starting_usd": "100",
        "ending_usd": str(ending),
        "cash_usd": events[-1]["cash_usd"] if events else "100",
        "holdings": events[-1]["holdings"] if events else {},
        "buys": buys,
        "sells": sells,
        "wins": _closed_trades(events, positive=True),
        "losses": _closed_trades(events, positive=False),
        "realized_pnl_usd": str(realized),
        "unrealized_pnl_usd": str(ending - Decimal("100") - realized),
        "costs_usd": str(costs),
        "max_drawdown": str(drawdown.quantize(Decimal("0.0001"))),
        "exposure_usd": str(
            max(Decimal("0"), ending - Decimal(events[-1]["cash_usd"])) if events else Decimal("0")
        ),
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
    if filled is None or not filled.get("session"):
        return None
    signal = date.fromisoformat(str(filled["session"]))
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
    event = _event(again, _SYNTHETIC, closes.get(signal))
    event["decision"] = "duplicate_prevented"
    event["status"] = "duplicate_prevented"
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


def _closed_trades(events: list[dict[str, Any]], *, positive: bool) -> int:
    count = 0
    for item in events:
        if item.get("side") != "sell":
            continue
        realized = Decimal(str(item["realized_pnl_usd"]))
        if positive and realized > 0:
            count += 1
        if not positive and realized < 0:
            count += 1
    return count


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
