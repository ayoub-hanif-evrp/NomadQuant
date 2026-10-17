"""Month-start pilot arming must be possible without tomorrow's fill bar.

An unstarted clock must not invent an October (or any past-month) trade.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore, StoredBar, content_hash
from nomadquant.shadow.cycle import LABEL_FORWARD, run_shadow_cycle
from nomadquant.shadow.pilot import confirm_pilot_start, pilot_start_preview, supervised_readiness
from nomadquant.shadow.store import ShadowStore
from tests.conftest import make_settings
from tests.shadow_support import grant_forward_approval

MONTH_START = date(2020, 2, 3)
FILL_DAY = date(2020, 2, 4)


def _bars(path: Path, start: date, end: date, *, rising: bool = True) -> None:
    sessions = sessions_between(start, end)
    store = MarketStore(path)
    rows: list[StoredBar] = []
    for index, session in enumerate(sessions):
        close = (
            Decimal("100") + Decimal(index) * Decimal("0.25")
            if rising
            else Decimal("180") - Decimal(index) * Decimal("0.05")
        )
        for symbol in ("SPY", "QQQ"):
            raw = StoredBar(
                symbol=symbol,
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
            rows.append(StoredBar(**{**raw.__dict__, "content_hash": content_hash(raw)}))
    store.write_bars(rows)


def _settings(tmp: Path, market_end: date, *, rising: bool = True):
    market = tmp / "market.sqlite"
    _bars(market, date(2018, 1, 2), market_end, rising=rising)
    ShadowStore(tmp / "shadow.sqlite", namespace="forward")
    return make_settings(tmp, market_data_path=str(market), shadow_path=str(tmp / "shadow.sqlite"))


def _arm(settings, now: datetime) -> dict:
    preview = pilot_start_preview(settings, now=now)
    return confirm_pilot_start(settings, preview["preview_hash"], now=now)


def test_month_start_before_open_can_arm_without_fill_bar(tmp_path: Path) -> None:
    settings = _settings(tmp_path, date(2020, 1, 31))
    morning = datetime(2020, 2, 3, 12, 0, tzinfo=UTC)
    ready = supervised_readiness(settings, now=morning)
    assert ready["state"] in {"WAITING_FOR_SESSION", "WAITING_FOR_DATA"}
    assert ready["rebalance_scheduled"] is False
    assert ready["armable"] is True
    armed = _arm(settings, morning)
    assert armed["applied"] is False
    assert armed["fill_grant_issued"] is False
    assert armed["status"] == "PILOT_ARMED"
    after = supervised_readiness(settings, now=morning)
    assert after["pilot_clock_started"] is True
    assert after["lifecycle"] == "PILOT_ARMED"
    store = ShadowStore(settings.shadow_path, namespace="forward")
    assert store.snapshot()["cash_usd"] == Decimal("100")
    assert store.list_cycles(limit=5) == []
    assert store.pending_intents() == []


def test_month_start_after_close_is_ready_without_next_open(tmp_path: Path) -> None:
    settings = _settings(tmp_path, MONTH_START)
    evening = datetime(2020, 2, 3, 22, 0, tzinfo=UTC)
    ready = supervised_readiness(settings, now=evening)
    assert ready["rebalance_scheduled"] is True
    assert ready["observation_available"] is False
    assert ready["state"] == "READY_TO_START"
    armed = _arm(settings, evening)
    assert armed["fill_grant_issued"] is True
    assert armed["applied"] is False


def test_arming_mid_month_does_not_invent_the_past_month_start(tmp_path: Path) -> None:
    settings = _settings(tmp_path, date(2020, 2, 14))
    now = datetime(2020, 2, 14, 22, 0, tzinfo=UTC)
    ready = supervised_readiness(settings, now=now)
    assert ready["rebalance_scheduled"] is False
    armed = _arm(settings, now)
    assert armed["status"] == "PILOT_ARMED"
    result = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=now,
    )
    store = ShadowStore(settings.shadow_path, namespace="forward")
    missed = [row for row in store.list_cycles(limit=20) if row["status"] == "missed_signal"]
    february = [
        row for row in store.list_cycles(limit=20) if row.get("signal_session") == "2020-02-03"
    ]
    assert february == []
    assert result["status"] in {"no_trade", "missed_signal", "blocked"}
    assert store.snapshot()["cash_usd"] == Decimal("100")
    assert store.snapshot()["holdings"] == {}
    assert missed == [] or all(row["fill_price"] is None for row in missed)


def test_following_session_before_open_stays_pending(tmp_path: Path) -> None:
    settings = _settings(tmp_path, MONTH_START)
    monday = datetime(2020, 2, 3, 22, 0, tzinfo=UTC)
    _arm(settings, monday)
    first = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=monday,
    )
    assert first["status"] in {"pending_data", "no_trade", "awaiting_approval"}
    tuesday_morning = datetime(2020, 2, 4, 12, 0, tzinfo=UTC)
    ready = supervised_readiness(settings, now=tuesday_morning)
    assert ready["state"] in {"PENDING_OBSERVATION", "PILOT_ARMED", "READY_TO_START"}


def test_valid_signal_records_then_fill_needs_a_grant(tmp_path: Path) -> None:
    settings = _settings(tmp_path, date(2020, 1, 31))
    friday = datetime(2020, 1, 31, 22, 0, tzinfo=UTC)
    armed = _arm(settings, friday)
    assert armed["fill_grant_issued"] is False
    _bars(Path(settings.market_data_path), MONTH_START, MONTH_START)
    monday = datetime(2020, 2, 3, 22, 0, tzinfo=UTC)
    first = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=monday,
    )
    store = ShadowStore(settings.shadow_path, namespace="forward")
    assert first["status"] in {"pending_data", "awaiting_approval"}
    assert store.snapshot()["cash_usd"] == Decimal("100")
    _bars(Path(settings.market_data_path), FILL_DAY, FILL_DAY)
    tuesday = datetime(2020, 2, 4, 22, 0, tzinfo=UTC)
    second = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
    )
    assert second["status"] != "filled"
    assert store.snapshot()["cash_usd"] == Decimal("100")
    grant_forward_approval(Path(settings.shadow_path), Path(settings.market_data_path), tuesday)
    third = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=tuesday,
    )
    assert third["status"] in {"filled", "no_trade", "risk_rejected", "awaiting_approval"}


def test_negative_momentum_is_no_trade_not_a_forced_buy(tmp_path: Path) -> None:
    settings = _settings(tmp_path, MONTH_START, rising=False)
    monday = datetime(2020, 2, 3, 22, 0, tzinfo=UTC)
    _arm(settings, monday)
    result = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=monday,
    )
    store = ShadowStore(settings.shadow_path, namespace="forward")
    assert result["status"] in {"no_trade", "pending_data"}
    if result["status"] == "no_trade":
        assert result["intent"] in {"no_trade", "hold"}
    assert store.snapshot()["holdings"] == {}
    assert store.snapshot()["cash_usd"] == Decimal("100")


def test_expired_fill_grant_does_not_simulate_a_fill(tmp_path: Path) -> None:
    settings = _settings(tmp_path, FILL_DAY)
    now = datetime(2020, 2, 4, 22, 0, tzinfo=UTC)
    _arm(settings, now)
    grant_forward_approval(Path(settings.shadow_path), Path(settings.market_data_path), now)
    later = now + timedelta(hours=2)
    result = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label=LABEL_FORWARD,
        as_of=later,
    )
    assert result["status"] != "filled"
    store = ShadowStore(settings.shadow_path, namespace="forward")
    assert store.snapshot()["cash_usd"] == Decimal("100")


def test_duplicate_apply_does_not_double_count(tmp_path: Path) -> None:
    settings = _settings(tmp_path, MONTH_START)
    monday = datetime(2020, 2, 3, 22, 0, tzinfo=UTC)
    _arm(settings, monday)
    kwargs = {
        "market_path": settings.market_data_path,
        "shadow_path": settings.shadow_path,
        "risk_path": settings.risk_path,
        "mode": "apply",
        "label": LABEL_FORWARD,
        "as_of": monday,
    }
    first = run_shadow_cycle(**kwargs)
    second = run_shadow_cycle(**kwargs)
    store = ShadowStore(settings.shadow_path, namespace="forward")
    cycles = [
        row
        for row in store.list_cycles(limit=20)
        if row.get("signal_session") == MONTH_START.isoformat() and row["status"] != "missed_signal"
    ]
    assert first["status"] == second["status"] or "Duplicate" in str(second.get("warnings"))
    assert len(cycles) <= 1


def test_missing_market_file_is_waiting_for_data_and_still_armable(tmp_path: Path) -> None:
    ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    settings = make_settings(tmp_path)
    now = datetime(2020, 2, 3, 22, 0, tzinfo=UTC)
    ready = supervised_readiness(settings, now=now)
    assert ready["state"] in {"WAITING_FOR_DATA", "NOT_CONFIGURED"}
    if ready["state"] == "WAITING_FOR_DATA":
        assert ready["armable"] is True
        armed = _arm(settings, now)
        assert armed["applied"] is False
        assert armed["status"] == "PILOT_ARMED"
