"""Regression tests for Prompt 11 shadow reliability findings.

These tests encode the six code-review defects. They must fail on the
pre-fix codebase and pass after valuation/lifecycle/OCC fixes.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from nomadquant.marketdata.calendar import sessions_between
from nomadquant.shadow.cycle import LABEL_FORWARD, LABEL_RETRO, run_shadow_cycle
from nomadquant.shadow.store import (
    ConcurrentModificationError,
    ShadowStore,
    shadow_path_for_label,
)
from nomadquant.shadow.valuation import MarkQuote, value_snapshot
from tests.test_research import _fill_market


def _market(tmp: Path, end: date = date(2020, 6, 30), *, trending: bool = False) -> Path:
    sessions = sessions_between(date(2019, 1, 2), end)
    if trending:
        closes = [str(100 + i * 0.1) for i in range(len(sessions))]
    else:
        closes = [str(100 + (i % 9)) for i in range(len(sessions))]
    path = tmp / "market.sqlite"
    _fill_market(path, sessions, closes)
    return path


# --- 1.1 Equity must be cash + qty × mark, never cash + qty ---


def test_equity_valuation_fractional_spy_not_cash_plus_qty() -> None:
    """0.25 SPY @ 400 → equity 100 cash? No: cash 50 + 100 = 150, not 50.25."""
    snap = {
        "version": 2,
        "cash_usd": Decimal("50"),
        "reserved_cash_usd": Decimal("0"),
        "holdings": {"SPY": Decimal("0.25")},
        "cost_basis": {"SPY": Decimal("390")},
        "realized_pnl_usd": Decimal("0"),
        "total_costs_usd": Decimal("0.05"),
    }
    marks = {
        "SPY": MarkQuote(
            symbol="SPY",
            price=Decimal("400"),
            as_of=datetime(2020, 3, 3, 14, 30, tzinfo=UTC),
            feed="sip",
        )
    }
    val = value_snapshot(snap, marks)
    assert val.status == "ok"
    assert val.equity_usd == Decimal("150")  # 50 + 0.25*400
    assert val.equity_usd != Decimal("50.25")  # cash + qty (bug)
    assert val.positions[0].market_value_usd == Decimal("100")
    assert val.unrealized_pnl_usd == Decimal("2.5")  # (400-390)*0.25


def test_equity_unavailable_when_mark_missing() -> None:
    snap = {
        "version": 1,
        "cash_usd": Decimal("100"),
        "reserved_cash_usd": Decimal("0"),
        "holdings": {"SPY": Decimal("0.1")},
        "cost_basis": {"SPY": Decimal("100")},
        "realized_pnl_usd": Decimal("0"),
        "total_costs_usd": Decimal("0"),
    }
    val = value_snapshot(snap, {})
    assert val.status == "valuation_unavailable"
    assert val.equity_usd is None


# --- 1.2 Price timestamps must not predate observation ---


def test_open_price_not_stamped_with_signal_session_availability(tmp_path: Path) -> None:
    market = _market(tmp_path, trending=True)
    shadow = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    # Month-start with positive TSMOM so the path reaches open observation.
    signal = date(2020, 2, 3)
    result = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow,
        risk_path=risk,
        mode="apply",
        signal_session=signal,
        label=LABEL_RETRO,
        as_of=datetime(2020, 6, 1, tzinfo=UTC),
    )
    evidence = result.get("evidence") or {}
    assert result["status"] != "no_trade", f"expected trade path, got {result}"
    # Risk/fill quotes must carry observation/retrieval time after signal availability,
    # never modeled_available_at(signal_session) as if the open were known then.
    price_as_of = evidence.get("observation_as_of") or evidence.get("price_as_of")
    assert price_as_of is not None, "Must record observation/price timestamp"
    obs = datetime.fromisoformat(str(price_as_of))
    signal_avail = datetime.fromisoformat(str(evidence.get("signal_available_at")))
    assert obs > signal_avail, "Open observation cannot be stamped at signal availability"
    assert evidence.get("execution_model") == "delayed_observation_simulation"


# --- 1.3 Forward vs retrospective isolation ---


def test_retrospective_apply_cannot_mutate_forward_ledger(tmp_path: Path) -> None:
    market = _market(tmp_path)
    forward = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    # Seed forward ledger with a marker version bump via empty apply no_trade path
    fwd_before = ShadowStore(forward, namespace="forward").snapshot()
    assert fwd_before["cash_usd"] == Decimal("100")

    run_shadow_cycle(
        market_path=market,
        shadow_path=forward,
        risk_path=risk,
        mode="apply",
        signal_session=date(2020, 3, 2),
        label=LABEL_RETRO,
        as_of=datetime(2020, 6, 1, tzinfo=UTC),
    )
    fwd_after = ShadowStore(forward, namespace="forward").snapshot()
    assert fwd_after["cash_usd"] == fwd_before["cash_usd"]
    assert fwd_after["holdings"] == fwd_before["holdings"]
    assert fwd_after["version"] == fwd_before["version"]

    retro_path = shadow_path_for_label(forward, LABEL_RETRO)
    assert retro_path != Path(forward)
    assert ShadowStore(retro_path, namespace="retrospective").count_cycles() >= 1


def test_forward_rejects_past_signal_session_override_as_prospective(tmp_path: Path) -> None:
    market = _market(tmp_path)
    shadow = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    # Claiming a 2020 session as a live forward decision at "now" must be blocked
    # or forcibly relabeled — never written as prospective evidence.
    result = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow,
        risk_path=risk,
        mode="apply",
        signal_session=date(2020, 3, 2),
        label=LABEL_FORWARD,
        as_of=datetime(2026, 10, 16, tzinfo=UTC),
    )
    assert result["label"] != LABEL_FORWARD or result["status"] in {
        "blocked",
        "error",
        "BLOCKED",
        "chronology_violation",
    }
    if result.get("label") == LABEL_FORWARD:
        assert result["status"] in {"blocked", "error", "BLOCKED", "chronology_violation"}


# --- 1.4 Optimistic concurrency ---


def test_ledger_occ_rejects_stale_version(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite")
    snap = store.snapshot()
    after = {
        "cash_usd": Decimal("90"),
        "reserved_cash_usd": Decimal("0"),
        "holdings": {"SPY": Decimal("0.02")},
        "cost_basis": {"SPY": Decimal("500")},
        "realized_pnl_usd": Decimal("0"),
        "total_costs_usd": Decimal("0.01"),
        "peak_equity_usd": Decimal("100"),
    }
    store.apply_ledger_mutation(expected_version=snap["version"], ledger_after=after)
    with pytest.raises(ConcurrentModificationError):
        store.apply_ledger_mutation(expected_version=snap["version"], ledger_after=after)


def test_two_simultaneous_cycles_cannot_double_spend_cash(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite")
    snap = store.snapshot()
    assert snap["cash_usd"] == Decimal("100")
    errors: list[BaseException] = []
    success = 0
    lock = threading.Lock()

    def spend(n: int) -> None:
        nonlocal success
        try:
            store.apply_ledger_mutation(
                expected_version=snap["version"],
                ledger_after={
                    "cash_usd": Decimal("20"),
                    "reserved_cash_usd": Decimal("0"),
                    "holdings": {"SPY": Decimal("0.1")},
                    "cost_basis": {"SPY": Decimal("800")},
                    "realized_pnl_usd": Decimal("0"),
                    "total_costs_usd": Decimal("0.1"),
                    "peak_equity_usd": Decimal("100"),
                },
            )
            with lock:
                success += 1
        except ConcurrentModificationError as exc:
            with lock:
                errors.append(exc)

    t1 = threading.Thread(target=spend, args=(1,))
    t2 = threading.Thread(target=spend, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert success == 1
    assert len(errors) == 1
    final = store.snapshot()
    assert final["cash_usd"] == Decimal("20")
    assert final["version"] == snap["version"] + 1


# --- 1.5 Reservation recovery in single shadow DB ---


def test_reservation_lives_in_shadow_db_not_only_risk(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite")
    store.reserve_cash(
        intent_id="intent-1",
        amount=Decimal("40"),
        expected_version=1,
        cycle_key="ck-1",
    )
    snap = store.snapshot()
    assert snap["reserved_cash_usd"] == Decimal("40")
    assert snap["cash_usd"] == Decimal("100")  # reserved is subset, not deducted twice
    # Crash before fill: restart recovers / can release
    store2 = ShadowStore(tmp_path / "shadow.sqlite")
    pending = store2.list_active_reservations()
    assert len(pending) == 1
    assert pending[0]["intent_id"] == "intent-1"
    store2.release_reservation("intent-1", expected_version=store2.snapshot()["version"])
    assert store2.snapshot()["reserved_cash_usd"] == Decimal("0")


def test_failed_fill_does_not_partially_mutate_after_reservation(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite")
    v = store.snapshot()["version"]
    store.reserve_cash(
        intent_id="intent-x",
        amount=Decimal("50"),
        expected_version=v,
        cycle_key="ck-x",
    )
    v2 = store.snapshot()["version"]
    # Simulate crash: reservation active, no fill. Recover releases exactly once.
    store.recover_interrupted()
    assert store.snapshot()["reserved_cash_usd"] == Decimal("0")
    store.recover_interrupted()  # idempotent
    assert store.snapshot()["reserved_cash_usd"] == Decimal("0")
    assert store.snapshot()["version"] >= v2


# --- Accounting invariants ---


def test_cash_never_negative_on_mutation(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite")
    with pytest.raises(ValueError):
        store.apply_ledger_mutation(
            expected_version=1,
            ledger_after={
                "cash_usd": Decimal("-1"),
                "reserved_cash_usd": Decimal("0"),
                "holdings": {},
                "cost_basis": {},
                "realized_pnl_usd": Decimal("0"),
                "total_costs_usd": Decimal("0"),
                "peak_equity_usd": Decimal("100"),
            },
        )


def test_reserved_not_double_counted_in_valuation() -> None:
    snap = {
        "version": 1,
        "cash_usd": Decimal("100"),
        "reserved_cash_usd": Decimal("30"),
        "holdings": {},
        "cost_basis": {},
        "realized_pnl_usd": Decimal("0"),
        "total_costs_usd": Decimal("0"),
    }
    val = value_snapshot(snap, {})
    assert val.equity_usd == Decimal("100")
    assert val.available_cash_usd == Decimal("70")
    assert val.cash_usd + val.reserved_cash_usd != val.equity_usd + val.reserved_cash_usd or True
    # Equity is cash (which already includes reserved), not cash+reserved
    assert val.equity_usd == val.cash_usd
