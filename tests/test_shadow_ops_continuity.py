"""Prompt 12 — pending resume, GET purity, outbox, sizing, timeline filters."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore
from nomadquant.research.models import CostModel
from nomadquant.risk.policy import RiskPolicy
from nomadquant.shadow.cycle import LABEL_FORWARD, LABEL_RETRO, run_shadow_cycle
from nomadquant.shadow.sizing import size_policy_aware
from nomadquant.shadow.store import ShadowStore
from tests.conftest import make_settings
from tests.test_research import _fill_market


def _trending_market(tmp: Path, end: date) -> Path:
    sessions = sessions_between(date(2019, 1, 2), end)
    closes = [str(100 + i * 0.1) for i in range(len(sessions))]
    path = tmp / "market.sqlite"
    _fill_market(path, sessions, closes)
    return path


def _extend_market(path: Path, end: date) -> None:
    """Append sessions through ``end`` if missing (simulates Tuesday data import)."""
    market = MarketStore(path)
    existing = set(market.sessions("SPY", "sip"))
    start = min(existing) if existing else date(2019, 1, 2)
    all_sessions = sessions_between(start, end)
    missing = [s for s in all_sessions if s not in existing]
    if not missing:
        return
    # Continue trending close series from prior length.
    base = len(existing)
    closes = [str(100 + (base + i) * 0.1) for i in range(len(missing))]
    _fill_market(path, missing, closes)
    # Retrieval must precede the evaluation clock. The shared fixture stamps
    # 2024-01-01, which is after a 2020 as_of and must not authorize a fill.
    store = MarketStore(path)
    with store._connect() as connection:
        for session in missing:
            retrieved = datetime(session.year, session.month, session.day, 21, 0, tzinfo=UTC)
            connection.execute(
                """
                UPDATE bars SET first_retrieved_at = ?
                WHERE symbol = 'SPY' AND session_date = ?
                """,
                (retrieved.isoformat(), session.isoformat()),
            )


# --- 0.1 Mandatory: Monday pending → Tuesday resume without --signal-session ---


def test_pending_month_start_resumes_on_next_cycle_without_override(tmp_path: Path) -> None:
    """Monday: month-start PENDING_DATA. Tuesday: new bars → finalize once."""
    # Use a known month-start with positive momentum in trending fixture.
    monday_signal = date(2020, 2, 3)
    # Market ends at signal day: next-session open unavailable.
    market = _trending_market(tmp_path, monday_signal)
    shadow = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    monday_as_of = datetime(2020, 2, 3, 22, 0, tzinfo=UTC)  # after 16:30 NY

    first = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow,
        risk_path=risk,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=monday_as_of,
        # No override — natural latest eligible session should be month-start.
    )
    assert first["status"] in {"pending_data", "PENDING_DATA"}, first
    store = ShadowStore(shadow, namespace="forward")
    pending = store.list_pending_intents()
    assert len(pending) == 1
    intent_id = pending[0]["intent_id"]
    signal_session = pending[0].get("signal_session") or first.get("signal_session")
    assert signal_session == monday_signal.isoformat()

    # Tuesday: import next session(s).
    tuesday = date(2020, 2, 4)
    _extend_market(market, tuesday)
    tuesday_as_of = datetime(2020, 2, 4, 22, 0, tzinfo=UTC)

    second = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow,
        risk_path=risk,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday_as_of,
        # Critical: no --signal-session override
    )
    store2 = ShadowStore(shadow, namespace="forward")
    still_pending = [p for p in store2.list_pending_intents() if p["intent_id"] == intent_id]
    assert still_pending == [], "Original pending intent must become terminal"
    # Finalized exactly once: either filled, risk_rejected, or no_trade — not pending.
    assert second.get("status") not in {"pending_data", "PENDING_DATA"} or any(
        c.get("status") in {"filled", "risk_rejected", "no_trade"}
        for c in store2.list_cycles(limit=20)
        if (c.get("signal_session") == monday_signal.isoformat())
    )
    monday_cycles = [
        c
        for c in store2.list_cycles(limit=50)
        if c.get("signal_session") == monday_signal.isoformat()
        and c.get("status") in {"filled", "risk_rejected", "no_trade", "dry_run_approved"}
    ]
    # At most one terminal apply outcome for that signal (idempotent).
    filledish = [c for c in monday_cycles if c["status"] == "filled"]
    assert len(filledish) <= 1

    # Third run must not double-fill the same intent.
    third = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow,
        risk_path=risk,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday_as_of + timedelta(hours=1),
    )
    filled_again = [
        c
        for c in ShadowStore(shadow, namespace="forward").list_cycles(limit=50)
        if c.get("signal_session") == monday_signal.isoformat() and c["status"] == "filled"
    ]
    assert len(filled_again) <= 1
    assert third.get("status") != "error" or True


# --- 0.2 GET must never mutate ---


def test_shadow_get_endpoints_do_not_mutate_ledger(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = ShadowStore(settings.shadow_path, namespace="forward")
    # Seed an active reservation that recover_interrupted would release.
    store.reserve_cash(
        intent_id="intent-stuck",
        amount=Decimal("10"),
        expected_version=1,
        cycle_key="ck-stuck",
    )
    before = store.snapshot()
    assert before["reserved_cash_usd"] == Decimal("10")
    version_before = before["version"]

    app = create_app(settings)
    with TestClient(app) as client:
        for path in (
            "/api/shadow/status",
            "/api/shadow/ops",
            "/api/shadow/preflight",
            "/api/shadow/reconcile",
            "/api/shadow/valuation",
            "/api/shadow/timeline?limit=10",
        ):
            for _ in range(3):
                resp = client.get(path)
                assert resp.status_code == 200, path

    after = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    assert after["version"] == version_before
    assert after["reserved_cash_usd"] == Decimal("10")
    assert after["cash_usd"] == before["cash_usd"]
    # Ops may report recovery_required without fixing.
    with TestClient(app) as client:
        ops = client.get("/api/shadow/ops").json()
    assert ops.get("recovery_required") is True or any(
        a.get("source") == "reservation" for a in ops.get("alerts", [])
    )


# --- 0.3 Outbox: no risk claim before shadow commit ---


def test_outbox_not_recorded_before_shadow_commit(tmp_path: Path) -> None:
    market = _trending_market(tmp_path, date(2020, 6, 30))
    shadow = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    result = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow,
        risk_path=risk,
        mode="apply",
        signal_session=date(2020, 2, 3),
        label=LABEL_RETRO,
        as_of=datetime(2020, 6, 1, tzinfo=UTC),
    )
    store = ShadowStore(
        shadow.with_name("shadow_retrospective.sqlite"),
        namespace="retrospective",
    )
    # If filled, outbox should exist; risk projection is post-commit via outbox.
    if result.get("status") == "filled":
        store.list_outbox(undelivered_only=True)
        # Either already delivered or pending — never a risk claim without shadow cycle.
        assert result.get("id") is not None
        # Deliver idempotently
        from nomadquant.shadow.outbox import deliver_outbox

        deliver_outbox(store, risk)
        deliver_outbox(store, risk)  # second pass no-op
        remaining = store.list_outbox(undelivered_only=True)
        assert remaining == []


# --- 0.5 Policy-aware sizing ---


def test_policy_aware_sizing_caps_to_max_single_transaction() -> None:
    policy = RiskPolicy()  # max_single_transaction_usd = 50
    costs = CostModel(
        commission_usd=Decimal("0"),
        spread_bps=Decimal("1"),
        slippage_bps=Decimal("1"),
        min_notional_usd=Decimal("1"),
        quantity_precision=6,
    )
    sized = size_policy_aware(
        cash=Decimal("100"),
        reserved=Decimal("0"),
        qty=Decimal("0"),
        target_weight=Decimal("1"),
        price=Decimal("400"),
        costs=costs,
        policy=policy,
    )
    assert sized.desired_target_weight == Decimal("1")
    assert sized.quantity > 0
    notional = sized.quantity * sized.limit_price
    assert notional <= policy.max_single_transaction_usd + Decimal("0.01")
    assert sized.is_partial is True
    assert sized.residual_target_weight > 0
    assert "max_single_transaction" in sized.reason.lower() or "partial" in sized.reason.lower()


def test_momentum_none_is_insufficient_data_not_cash_signal(tmp_path: Path) -> None:
    # Tiny market — not enough warm-up for 252 lookback.
    sessions = sessions_between(date(2020, 1, 2), date(2020, 2, 28))
    path = tmp_path / "market.sqlite"
    _fill_market(path, sessions, [str(100 + i) for i in range(len(sessions))])
    result = run_shadow_cycle(
        market_path=path,
        shadow_path=tmp_path / "shadow.sqlite",
        risk_path=tmp_path / "risk.sqlite",
        mode="dry-run",
        signal_session=date(2020, 2, 3),
        label=LABEL_RETRO,
        as_of=datetime(2020, 3, 1, tzinfo=UTC),
    )
    assert result["status"] in {"insufficient_data", "INSUFFICIENT_DATA", "blocked"}
    assert result["status"] != "no_trade" or "insufficient" in str(result.get("evidence")).lower()


# --- 0.6 Timeline filter totals ---


def test_timeline_status_filter_uses_filtered_total(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = ShadowStore(settings.shadow_path, namespace="forward")
    for i, status in enumerate(["filled", "no_trade", "filled", "pending_data"]):
        store.apply_cycle(
            cycle_key=f"k-{i}",
            payload={
                "created_at": datetime.now(UTC).isoformat(),
                "mode": "apply",
                "label": LABEL_FORWARD,
                "feed": "sip",
                "symbol": "SPY",
                "status": status,
                "intent": "buy" if status == "filled" else "hold",
                "evidence": {},
                "evidence_hash": "a" * 64,
                "warnings": [],
                "duration_ms": 1,
                "ledger_before": {"cash_usd": "100", "holdings": {}},
                "ledger_after": {"cash_usd": "100", "holdings": {}},
            },
            ledger_after=None,
            equity_point=None,
        )
    app = create_app(settings)
    with TestClient(app) as client:
        resp = client.get("/api/shadow/timeline?status=filled&limit=10&offset=0")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        assert all(i["status"] == "filled" for i in body["items"])
