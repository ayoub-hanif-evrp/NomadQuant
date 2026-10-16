"""Missed month-start rebalances must be visible and must not be backfilled."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore, StoredBar, content_hash
from nomadquant.shadow.cycle import LABEL_FORWARD, run_shadow_cycle
from nomadquant.shadow.store import ShadowStore
from tests.shadow_support import grant_forward_approval


def _market(path: Path, start: date, end: date) -> None:
    sessions = sessions_between(start, end)
    store = MarketStore(path)
    bars: list[StoredBar] = []
    for index, session in enumerate(sessions):
        close = Decimal("100") + Decimal(index) * Decimal("0.1")
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


def test_shutdown_on_month_start_is_missed_not_backfilled(tmp_path: Path) -> None:
    """Down on the first February session; back on Feb 5. Do not invent the trade."""
    market = tmp_path / "market.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"
    _market(market, date(2019, 11, 1), date(2020, 2, 5))
    shadow = ShadowStore(shadow_path, namespace="forward")
    with shadow._connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO shadow_meta (key, value) VALUES (?, ?)",
            ("forward_pilot_started_at", "2020-01-15T00:00:00+00:00"),
        )
    before = shadow.snapshot()
    as_of = datetime(2020, 2, 5, 22, tzinfo=UTC)
    grant_forward_approval(shadow_path, market, as_of)

    run_shadow_cycle(
        market_path=market,
        shadow_path=shadow_path,
        risk_path=tmp_path / "risk.sqlite",
        mode="apply",
        label=LABEL_FORWARD,
        as_of=as_of,
    )

    missed = [
        row
        for row in ShadowStore(shadow_path, namespace="forward").list_cycles(limit=20)
        if row["status"] == "missed_signal" and row["signal_session"] == "2020-02-03"
    ]
    assert missed, "February month-start was skipped and is not visible"
    evidence = missed[0]["evidence"]
    assert evidence["classification"] == "missed_signal"
    assert missed[0]["fill_price"] is None
    assert missed[0]["fill_qty"] is None
    detected = datetime.fromisoformat(missed[0]["created_at"])
    assert detected > datetime(2020, 2, 4, tzinfo=UTC)
    assert evidence.get("decision_produced_at") != evidence.get("signal_available_at")
    after = ShadowStore(shadow_path, namespace="forward").snapshot()
    assert after["cash_usd"] == before["cash_usd"] == Decimal("100")
    assert after["holdings"] == {}
    assert after["reserved_cash_usd"] == Decimal("0")


def test_two_day_outage_does_not_fill_the_old_open(tmp_path: Path) -> None:
    market = tmp_path / "market.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"
    _market(market, date(2019, 11, 1), date(2020, 2, 3))
    ShadowStore(shadow_path, namespace="forward").set_meta(
        "forward_pilot_started_at", "2020-01-15T00:00:00+00:00"
    )
    as_of = datetime(2020, 2, 5, 22, tzinfo=UTC)
    grant_forward_approval(shadow_path, market, as_of)
    run_shadow_cycle(
        market_path=market,
        shadow_path=shadow_path,
        risk_path=tmp_path / "risk.sqlite",
        mode="apply",
        label=LABEL_FORWARD,
        as_of=as_of,
    )
    store = ShadowStore(shadow_path, namespace="forward")
    missed = [row for row in store.list_cycles(limit=20) if row["status"] == "missed_signal"]
    assert [row["signal_session"] for row in missed] == ["2020-02-03"]
    assert store.snapshot()["cash_usd"] == Decimal("100")
    assert all(row["fill_price"] is None for row in missed)


def test_month_change_over_weekend_is_the_first_session(tmp_path: Path) -> None:
    """2020-03-01 was a Sunday. The scheduled session is Monday 2020-03-02."""
    market = tmp_path / "market.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"
    _market(market, date(2019, 11, 1), date(2020, 3, 4))
    ShadowStore(shadow_path, namespace="forward").set_meta(
        "forward_pilot_started_at", "2020-02-15T00:00:00+00:00"
    )
    grant_forward_approval(shadow_path, market, datetime(2020, 3, 4, 22, tzinfo=UTC))
    run_shadow_cycle(
        market_path=market,
        shadow_path=shadow_path,
        risk_path=tmp_path / "risk.sqlite",
        mode="apply",
        label=LABEL_FORWARD,
        as_of=datetime(2020, 3, 4, 22, tzinfo=UTC),
    )
    missed = [
        row["signal_session"]
        for row in ShadowStore(shadow_path, namespace="forward").list_cycles(limit=20)
        if row["status"] == "missed_signal"
    ]
    assert missed == ["2020-03-02"]


def test_duplicate_detection_does_not_repeat_the_miss(tmp_path: Path) -> None:
    market = tmp_path / "market.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    _market(market, date(2019, 11, 1), date(2020, 2, 5))
    ShadowStore(shadow_path, namespace="forward").set_meta(
        "forward_pilot_started_at", "2020-01-15T00:00:00+00:00"
    )
    grant_forward_approval(shadow_path, market, datetime(2020, 2, 5, 22, tzinfo=UTC))
    kwargs = {
        "market_path": market,
        "shadow_path": shadow_path,
        "risk_path": risk,
        "mode": "apply",
        "label": LABEL_FORWARD,
        "as_of": datetime(2020, 2, 5, 22, tzinfo=UTC),
    }
    run_shadow_cycle(**kwargs)
    run_shadow_cycle(**kwargs)
    missed = [
        row
        for row in ShadowStore(shadow_path, namespace="forward").list_cycles(limit=20)
        if row["status"] == "missed_signal"
    ]
    assert len(missed) == 1


def test_first_contact_does_not_backfill_history(tmp_path: Path) -> None:
    market = tmp_path / "market.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"
    _market(market, date(2019, 11, 1), date(2020, 2, 5))
    as_of = datetime(2020, 2, 5, 22, tzinfo=UTC)
    blocked = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow_path,
        risk_path=tmp_path / "risk.sqlite",
        mode="apply",
        label=LABEL_FORWARD,
        as_of=as_of,
    )
    assert blocked["status"] == "blocked"
    store = ShadowStore(shadow_path, namespace="forward")
    assert store.get_meta("forward_pilot_started_at") is None
    grant_forward_approval(shadow_path, market, as_of)
    run_shadow_cycle(
        market_path=market,
        shadow_path=shadow_path,
        risk_path=tmp_path / "risk.sqlite",
        mode="apply",
        label=LABEL_FORWARD,
        as_of=as_of,
    )
    store = ShadowStore(shadow_path, namespace="forward")
    assert store.get_meta("forward_pilot_started_at") == "2020-02-05T22:00:00+00:00"
    assert [row for row in store.list_cycles(limit=20) if row["status"] == "missed_signal"] == []


def test_same_day_month_start_is_prospective_not_missed(tmp_path: Path) -> None:
    market = tmp_path / "market.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"
    _market(market, date(2018, 1, 2), date(2020, 2, 3))
    ShadowStore(shadow_path, namespace="forward").set_meta(
        "forward_pilot_started_at", "2020-01-15T00:00:00+00:00"
    )
    grant_forward_approval(shadow_path, market, datetime(2020, 2, 3, 22, tzinfo=UTC))
    result = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow_path,
        risk_path=tmp_path / "risk.sqlite",
        mode="apply",
        label=LABEL_FORWARD,
        as_of=datetime(2020, 2, 3, 22, tzinfo=UTC),
    )
    store = ShadowStore(shadow_path, namespace="forward")
    assert result["status"] != "missed_signal"
    assert [row for row in store.list_cycles(limit=20) if row["status"] == "missed_signal"] == []
    assert store.pending_intents() or result["status"] in {"pending_data", "no_trade", "filled"}


def test_pending_month_start_resumes_and_is_not_missed(tmp_path: Path) -> None:
    market = tmp_path / "market.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    _market(market, date(2018, 1, 2), date(2020, 2, 3))
    store = ShadowStore(shadow_path, namespace="forward")
    store.set_meta("forward_pilot_started_at", "2020-01-15T00:00:00+00:00")
    grant_forward_approval(shadow_path, market, datetime(2020, 2, 3, 22, tzinfo=UTC))
    first = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow_path,
        risk_path=risk,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=datetime(2020, 2, 3, 22, tzinfo=UTC),
    )
    assert first["status"] == "pending_data"
    _market(market, date(2018, 1, 2), date(2020, 2, 4))
    second = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow_path,
        risk_path=risk,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=datetime(2020, 2, 4, 22, tzinfo=UTC),
    )
    again = ShadowStore(shadow_path, namespace="forward")
    assert second["status"] != "missed_signal"
    assert [row for row in again.list_cycles(limit=20) if row["status"] == "missed_signal"] == []
    assert again.snapshot()["cash_usd"] <= Decimal("100")
