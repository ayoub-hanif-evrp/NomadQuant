"""Isolated retrospective lifecycle. Does not touch the workstation forward ledger."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.config import Settings
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore, StoredBar, content_hash
from nomadquant.research.signals import momentum_return
from nomadquant.shadow.cycle import (
    LABEL_RETRO,
    LOOKBACK,
    SKIP,
    run_shadow_cycle,
    shadow_path_for_label,
)
from nomadquant.shadow.store import ShadowStore
from nomadquant.shadow.verify import verify_cycle

CONTEXT = "RETROSPECTIVE_TEST"


def _price(index: int) -> Decimal:
    if index < 180:
        return Decimal("100")
    if index < 260:
        return Decimal("100") + Decimal(index - 180) * Decimal("0.5")
    fallen = Decimal("140") - Decimal(index - 260) * Decimal("0.35")
    return fallen if fallen > Decimal("20") else Decimal("20")


def _write_market(path: Path, sessions: list[date], end: date | None = None) -> None:
    store = MarketStore(path)
    bars: list[StoredBar] = []
    for index, session in enumerate(sessions):
        if end is not None and session > end:
            break
        close = _price(index)
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
            first_retrieved_at=datetime(
                session.year, session.month, session.day, 21, 0, tzinfo=UTC
            ),
            content_hash="pending",
        )
        bars.append(StoredBar(**{**raw.__dict__, "content_hash": content_hash(raw)}))
    store.write_bars(bars)


def _month_starts(sessions: list[date]) -> list[date]:
    starts: list[date] = []
    for session in sessions:
        prior = [item for item in sessions if item < session]
        if not prior or prior[-1].month != session.month:
            starts.append(session)
    return starts


def _clock(session: date) -> datetime:
    return datetime(session.year, session.month, session.day, 22, 0, tzinfo=UTC)


def _apply(market: Path, shadow: Path, risk: Path, signal: date, sessions: list[date]) -> dict:
    nxt = next(session for session in sessions if session > signal)
    return run_shadow_cycle(
        market_path=market,
        shadow_path=shadow,
        risk_path=risk,
        mode="apply",
        as_of=_clock(nxt),
        signal_session=signal,
        label=LABEL_RETRO,
        context=CONTEXT,
    )


def test_isolated_buy_hold_sell_matches_and_detects_corruption(tmp_path: Path) -> None:
    sessions = sessions_between(date(2018, 1, 2), date(2019, 9, 1))
    closes = {session: _price(index) for index, session in enumerate(sessions)}
    starts = [
        session
        for session in _month_starts(sessions)
        if sessions.index(session) >= LOOKBACK + SKIP + 1
    ]
    buy_day = next(
        session
        for session in starts
        if (momentum_return(closes, sessions, session, LOOKBACK, SKIP) or 0) > 0
    )
    sell_day = next(
        session
        for session in starts
        if session > buy_day
        and (momentum_return(closes, sessions, session, LOOKBACK, SKIP) or 0) < 0
    )
    hold_day = next(
        session for session in sessions if buy_day < session < sell_day and session not in starts
    )
    market = tmp_path / "market.sqlite"
    shadow = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    _write_market(market, sessions)

    buy = _apply(market, shadow, risk, buy_day, sessions)
    assert buy["status"] == "filled", buy.get("warnings")
    assert buy["evidence"]["evaluation_context"] == CONTEXT
    ledger = shadow_path_for_label(shadow, LABEL_RETRO)
    store = ShadowStore(ledger, namespace="retrospective")
    after_buy = store.snapshot()
    assert after_buy["cash_usd"] < Decimal("100")
    assert after_buy["cash_usd"] >= Decimal("5")
    assert after_buy["holdings"]["SPY"] > 0
    assert after_buy["reserved_cash_usd"] == 0

    hold = _apply(market, shadow, risk, hold_day, sessions)
    assert hold["status"] == "no_trade"
    assert store.snapshot()["holdings"] == after_buy["holdings"]
    assert store.snapshot()["cash_usd"] == after_buy["cash_usd"]

    sell = _apply(market, shadow, risk, sell_day, sessions)
    assert sell["status"] == "filled", sell.get("warnings")
    after_sell = store.snapshot()
    assert after_sell["holdings"] == {}
    assert after_sell["realized_pnl_usd"] != 0

    duplicate = _apply(market, shadow, risk, buy_day, sessions)
    assert duplicate["id"] == buy["id"]
    assert store.snapshot()["cash_usd"] == after_sell["cash_usd"]

    version = store.snapshot()["version"]
    store.reserve_cash(
        intent_id="intent:interrupted",
        amount=Decimal("1"),
        expected_version=version,
        cycle_key="interrupted",
    )
    assert store.list_active_reservations()
    recovered = store.recover_interrupted()
    assert recovered["released_intent_ids"] == ["intent:interrupted"]
    assert store.list_active_reservations() == []
    assert store.snapshot()["holdings"] == after_sell["holdings"]
    assert store.snapshot()["cash_usd"] == after_sell["cash_usd"]

    settings = Settings(
        market_data_path=str(market),
        shadow_path=str(ledger),
        risk_path=str(risk),
    )
    report = verify_cycle(settings, int(buy["id"]))
    assert report["status"] == "PASS", report
    sell_report = verify_cycle(settings, int(sell["id"]))
    assert sell_report["status"] == "PASS", sell_report
    hold_report = verify_cycle(settings, int(hold["id"]))
    assert hold_report["status"] == "PASS", hold_report
    assert any(
        row["name"] == "fill_assumption" and row["status"] == "NOT_APPLICABLE"
        for row in hold_report["checks"]
    )

    detected = {
        "cash": _tamper_after(store, int(buy["id"]), settings, "cash_usd", "1", "cash_after"),
        "holdings": _tamper_after(
            store, int(buy["id"]), settings, "holdings", {"SPY": "9"}, "holdings_after"
        ),
        "cost_basis": _tamper_after(
            store, int(buy["id"]), settings, "cost_basis", {"SPY": "1"}, "cost_basis"
        ),
        "realized_pnl": _tamper_after(
            store, int(buy["id"]), settings, "realized_pnl_usd", "50", "realized_pnl"
        ),
        "total_costs": _tamper_after(
            store, int(buy["id"]), settings, "total_costs_usd", "50", "total_costs"
        ),
        "fill_price": _tamper_column(
            store, int(buy["id"]), settings, "fill_price", "1", "fill_recompute"
        ),
        "quantity": _tamper_column(
            store, int(buy["id"]), settings, "fill_qty", "9", "fill_quantity"
        ),
        "timestamp": _tamper_evidence(
            store, int(buy["id"]), settings, "risk_evaluated_at", "not-a-time"
        ),
        "policy_hash": _tamper_evidence(store, int(buy["id"]), settings, "policy_hash", "0" * 64),
        "execution_convention": _tamper_evidence(
            store, int(buy["id"]), settings, "execution_convention", "tampered"
        ),
    }
    assert all(detected.values()), detected
    scenarios = {
        "buy": "PASS",
        "hold_no_trade": "PASS",
        "partial_or_full_sell": "PASS",
        "duplicate_apply": "PASS",
        "interrupted_reservation_recovery": "PASS",
        "independent_buy_verification": "PASS",
        "independent_sell_verification": "PASS",
        "hold_fill_not_applicable": "PASS",
        "corruptions_detected": detected,
        "pending_observation": "SEE_PENDING_TEST",
        "live_forward_ledger": "NOT_TESTED",
    }
    (tmp_path / "lifecycle-report.json").write_text(
        json.dumps(scenarios, indent=2), encoding="utf-8"
    )


def _restore_cycle(store: ShadowStore, cycle_id: int, original: dict) -> None:
    with store._connect() as conn:  # noqa: SLF001
        conn.execute(
            """
            UPDATE shadow_cycles
            SET ledger_after_json = ?, evidence_json = ?, evidence_hash = ?,
                fill_price = ?, fill_qty = ?
            WHERE id = ?
            """,
            (
                json.dumps(original["ledger_after"]),
                json.dumps(original["evidence"]),
                original["evidence_hash"],
                original["fill_price"],
                original["fill_qty"],
                cycle_id,
            ),
        )


def _tamper_after(store, cycle_id, settings, field, value, check: str) -> bool:
    original = store.get_cycle(cycle_id)
    after = dict(original["ledger_after"])
    after[field] = value
    with store._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE shadow_cycles SET ledger_after_json = ? WHERE id = ?",
            (json.dumps(after), cycle_id),
        )
    report = verify_cycle(settings, cycle_id)
    found = any(row["name"] == check and row["status"] == "FAIL" for row in report["checks"])
    _restore_cycle(store, cycle_id, original)
    return report["status"] == "FAIL" and found


def _tamper_column(store, cycle_id, settings, column: str, value: str, check: str) -> bool:
    original = store.get_cycle(cycle_id)
    with store._connect() as conn:  # noqa: SLF001
        conn.execute(
            f"UPDATE shadow_cycles SET {column} = ? WHERE id = ?",
            (value, cycle_id),
        )
    report = verify_cycle(settings, cycle_id)
    found = any(row["name"] == check and row["status"] == "FAIL" for row in report["checks"])
    _restore_cycle(store, cycle_id, original)
    return report["status"] == "FAIL" and found


def _tamper_evidence(store, cycle_id, settings, field: str, value: str) -> bool:
    original = store.get_cycle(cycle_id)
    evidence = dict(original["evidence"])
    evidence[field] = value
    with store._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE shadow_cycles SET evidence_json = ? WHERE id = ?",
            (json.dumps(evidence), cycle_id),
        )
    report = verify_cycle(settings, cycle_id)
    found = any(
        row["name"] in {field, "evidence_hash", "signal_timing", "policy_hash", "fill_recompute"}
        and row["status"] in {"FAIL", "NOT_EVALUABLE", "INVALID_ARTIFACT"}
        for row in report["checks"]
    )
    _restore_cycle(store, cycle_id, original)
    return report["status"] != "PASS" and found


def test_pending_observation_resumes_without_a_backfill(tmp_path: Path) -> None:
    sessions = sessions_between(date(2018, 1, 2), date(2019, 6, 1))
    closes = {session: _price(index) for index, session in enumerate(sessions)}
    buy_day = next(
        session
        for session in _month_starts(sessions)
        if sessions.index(session) >= LOOKBACK + SKIP + 1
        and (momentum_return(closes, sessions, session, LOOKBACK, SKIP) or 0) > 0
    )
    market = tmp_path / "market.sqlite"
    shadow = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    _write_market(market, sessions, end=buy_day)
    waiting = _apply(market, shadow, risk, buy_day, sessions)
    assert waiting["status"] == "pending_data", waiting.get("warnings")
    assert waiting.get("fill_price") in {None, ""}
    _write_market(market, sessions)
    filled = _apply(market, shadow, risk, buy_day, sessions)
    assert filled["status"] == "filled", filled.get("warnings")
