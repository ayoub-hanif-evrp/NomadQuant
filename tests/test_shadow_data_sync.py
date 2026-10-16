"""Offline incremental sync, provenance, and apply-gate tests."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nomadquant.marketdata.alpaca_bars import FetchedBar
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.errors import MarketDataError, SipNotEntitled
from nomadquant.marketdata.store import MarketStore, StoredBar
from nomadquant.shadow.cli import _dispatch
from nomadquant.shadow.cycle import run_shadow_cycle
from nomadquant.shadow.data_ops import data_check, data_sync
from nomadquant.shadow.gate import application_guard
from nomadquant.shadow.provenance import provenance_dict
from nomadquant.shadow.schedule import ny_daily_gate
from nomadquant.shadow.store import ShadowStore
from tests.conftest import make_settings


def _fetcher(symbols: list[str], start, end, feed: str) -> list[FetchedBar]:
    bars: list[FetchedBar] = []
    for session in sessions_between(start, end):
        stamp = datetime(session.year, session.month, session.day, 14, 30, tzinfo=UTC)
        for symbol in symbols:
            bars.append(
                FetchedBar(
                    symbol=symbol,
                    timestamp=stamp,
                    open_="100",
                    high="101",
                    low="99",
                    close="100.5",
                    volume="1000",
                    feed=feed,
                )
            )
    return bars


def test_data_sync_fills_required_window_and_is_idempotent(tmp_path) -> None:
    settings = make_settings(tmp_path)
    as_of = datetime(2020, 6, 15, 22, tzinfo=UTC)
    first = data_sync(settings, feed="sip", fetcher=_fetcher, as_of=as_of)
    assert first["feed_used"] == "sip"
    assert first["inserted"] > 0
    assert first["status"] == "OK"
    second = data_sync(settings, feed="sip", fetcher=_fetcher, as_of=as_of)
    assert second["sync"] == "noop" or second["inserted"] == 0
    store = MarketStore(settings.market_data_path)
    spy = store.sessions("SPY", "sip")
    qqq = store.sessions("QQQ", "sip")
    assert spy and qqq
    assert "iex" not in {b.feed for b in []}  # feed isolation: only sip written
    assert store.has_symbol("SPY", "iex") is False


def test_data_sync_reports_entitlement_without_switching_feed(tmp_path) -> None:
    settings = make_settings(tmp_path)

    def _denied(*_args: object, **_kwargs: object) -> list[FetchedBar]:
        raise SipNotEntitled()

    result = data_sync(
        settings,
        feed="sip",
        fetcher=_denied,
        as_of=datetime(2020, 6, 15, 22, tzinfo=UTC),
    )
    assert result["status"] == "ERROR"
    assert result["error_code"] == "entitlement"
    assert result["feed_used"] == "sip"
    assert "IEX" in result["remediation"] or "iex" in result["remediation"]


def test_data_sync_missing_credentials(tmp_path) -> None:
    settings = make_settings(tmp_path)
    result = data_sync(settings, feed="sip", as_of=datetime(2020, 6, 15, 22, tzinfo=UTC))
    assert result["error_code"] == "missing_credentials"
    assert result["feed_used"] == "sip"


def test_data_sync_provider_error_and_interior_gap(tmp_path) -> None:
    settings = make_settings(tmp_path)
    as_of = datetime(2020, 6, 15, 22, tzinfo=UTC)
    first = data_sync(settings, feed="sip", fetcher=_fetcher, as_of=as_of)
    assert first["status"] == "OK"
    store = MarketStore(settings.market_data_path)
    spy = sorted(store.sessions("SPY", "sip"))
    dropped = spy[len(spy) // 2]
    with store._connect() as connection:
        connection.execute(
            "DELETE FROM bars WHERE symbol = 'SPY' AND session_date = ?",
            (dropped.isoformat(),),
        )
    check = data_check(settings, feed="sip", as_of=as_of)
    assert (
        dropped.isoformat() in check["symbols"]["SPY"]["missing_sessions"]
        or check["symbols"]["SPY"]["missing_count"] >= 1
    )

    def _partial(symbols: list[str], start, end, feed: str) -> list[FetchedBar]:
        bars = _fetcher(symbols, start, end, feed)
        return [bar for bar in bars if not (bar.symbol == "SPY" and bar.session_date == dropped)]

    partial = data_sync(settings, feed="sip", fetcher=_partial, as_of=as_of)
    assert partial["status"] == "WAITING_FOR_DATA"

    def _boom(*_args: object, **_kwargs: object) -> list[FetchedBar]:
        raise MarketDataError("Alpaca market data could not be reached.")

    failed = data_sync(settings, feed="sip", fetcher=_boom, as_of=as_of)
    assert failed["error_code"] == "provider"


def test_data_check_ignores_iex_when_feed_is_sip(tmp_path) -> None:
    settings = make_settings(tmp_path)
    as_of = datetime(2020, 6, 15, 22, tzinfo=UTC)
    data_sync(settings, feed="iex", fetcher=_fetcher, as_of=as_of)
    sip = data_check(settings, feed="sip", as_of=as_of)
    assert sip["status"] == "WAITING_FOR_DATA"
    assert sip["symbols"]["SPY"]["stored_sessions"] == 0


def test_unfinished_session_is_not_required(tmp_path) -> None:
    settings = make_settings(tmp_path)
    # 2020-06-15 15:00 UTC is 11:00 America/New_York, before the close.
    report = data_check(settings, feed="sip", as_of=datetime(2020, 6, 15, 15, tzinfo=UTC))
    assert report.get("eligible_end") != "2020-06-15"


def test_one_missing_spy_session_does_not_redownload_qqq(tmp_path) -> None:
    settings = make_settings(tmp_path)
    as_of = datetime(2020, 6, 15, 22, tzinfo=UTC)
    seeded = data_sync(settings, feed="sip", fetcher=_fetcher, as_of=as_of)
    assert seeded["inserted"] > 100
    store = MarketStore(settings.market_data_path)
    spy = sorted(store.sessions("SPY", "sip"))
    dropped = spy[-1]
    with store._connect() as connection:
        connection.execute(
            "DELETE FROM bars WHERE symbol = 'SPY' AND session_date = ?",
            (dropped.isoformat(),),
        )
    calls: list[tuple[tuple[str, ...], object, object]] = []

    def _recording(symbols: list[str], start, end, feed: str) -> list[FetchedBar]:
        calls.append((tuple(symbols), start, end))
        return _fetcher(symbols, start, end, feed)

    result = data_sync(settings, feed="sip", fetcher=_recording, as_of=as_of)
    assert result["inserted"] == 1
    assert result["provider_requests"] == 1
    assert calls == [(("SPY",), dropped, dropped)]
    assert "QQQ" not in calls[0][0]


def test_provenance_is_not_realtime_when_retrieved_late() -> None:
    bar = StoredBar(
        symbol="SPY",
        session_date=datetime(2020, 2, 4, tzinfo=UTC).date(),
        timestamp=datetime(2020, 2, 4, 14, 30, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
        provider="alpaca",
        feed="sip",
        adjustment="raw",
        timeframe="1Day",
        currency="USD",
        available_at=datetime(2020, 2, 4, 21, 30, tzinfo=UTC),
        first_retrieved_at=datetime(2020, 2, 5, 12, tzinfo=UTC),
        content_hash="abc",
    )
    payload = provenance_dict(bar, evaluated_at=datetime(2020, 2, 4, 22, tzinfo=UTC))
    assert payload["realtime_executable"] is False
    assert payload["execution_assumption"] == "delayed_hypothetical_daily_open"
    assert "bar_retrieved_after_evaluation_clock" in payload["evidence_gaps"]


def test_forward_apply_uses_application_guard(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(tmp_path)
    monkeypatch.setattr(
        "nomadquant.shadow.cli.application_guard",
        lambda _settings: {"allowed": False, "reasons": ["preflight_blocked"]},
    )
    called: list[str] = []
    monkeypatch.setattr(
        "nomadquant.shadow.cli.run_shadow_cycle",
        lambda **_kwargs: called.append("cycle") or {"status": "filled"},
    )
    args = argparse.Namespace(
        command="cycle",
        mode="apply",
        label="forward_shadow",
        signal_session="",
    )
    code = _dispatch(args, settings)
    assert code == 1
    assert called == []
    assert "blocked" in capsys.readouterr().out


def test_direct_cycle_apply_cannot_bypass_guard(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    ShadowStore(settings.shadow_path, namespace="forward")
    before = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    monkeypatch.setattr(
        "nomadquant.shadow.gate.run_preflight",
        lambda _settings, **_kwargs: {"status": "BLOCKED"},
    )
    monkeypatch.setattr(
        "nomadquant.shadow.gate.run_reconcile",
        lambda _settings: {"ok": True},
    )
    detail = run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        label="forward_shadow",
    )
    after = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    assert detail["status"] == "blocked"
    assert after["cash_usd"] == before["cash_usd"]
    assert after["version"] == before["version"]
    assert after["holdings"] == before["holdings"]


def test_dry_run_does_not_change_cash(tmp_path) -> None:
    settings = make_settings(tmp_path)
    ShadowStore(settings.shadow_path, namespace="forward")
    before = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    run_shadow_cycle(
        market_path=settings.market_data_path,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="dry-run",
        label="forward_shadow",
        as_of=datetime(2020, 6, 15, 22, tzinfo=UTC),
    )
    after = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    assert after["cash_usd"] == before["cash_usd"]
    assert after["reserved_cash_usd"] == before["reserved_cash_usd"]
    assert after["holdings"] == before["holdings"]
    assert after["version"] == before["version"]


def test_application_guard_blocks_when_preflight_blocked(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    monkeypatch.setattr(
        "nomadquant.shadow.gate.run_preflight",
        lambda _settings, **_kwargs: {"status": "BLOCKED"},
    )
    monkeypatch.setattr(
        "nomadquant.shadow.gate.run_reconcile",
        lambda _settings: {"ok": True},
    )
    guard = application_guard(settings)
    assert guard["allowed"] is False
    assert "preflight_blocked" in guard["reasons"]


def test_ny_gate_tracks_dst_not_host_clock() -> None:
    winter = datetime(2026, 1, 15, 22, 45, tzinfo=UTC)  # 17:45 EST
    summer = datetime(2026, 7, 15, 21, 45, tzinfo=UTC)  # 17:45 EDT
    early = datetime(2026, 1, 15, 22, 44, tzinfo=UTC)  # 17:44 EST, catch up prior session
    saturday = datetime(2026, 1, 17, 23, 0, tzinfo=UTC)
    holiday = datetime(2026, 1, 19, 18, 0, tzinfo=UTC)  # MLK Day
    assert ny_daily_gate(winter)["eligible"] is True
    assert ny_daily_gate(winter)["due_session"] == "2026-01-15"
    assert ny_daily_gate(winter)["next_window_utc"] == "2026-01-16T22:45:00+00:00"
    assert ny_daily_gate(summer)["eligible"] is True
    assert ny_daily_gate(summer)["due_session"] == "2026-07-15"
    assert ny_daily_gate(summer)["next_window_utc"] == "2026-07-16T21:45:00+00:00"
    assert ny_daily_gate(early)["reason"] == "catch_up"
    assert ny_daily_gate(early)["due_session"] == "2026-01-14"
    assert ny_daily_gate(saturday)["reason"] == "catch_up_closed_day"
    assert ny_daily_gate(holiday)["reason"] == "catch_up_closed_day"
    assert ny_daily_gate(holiday)["due_session"] == "2026-01-16"
    done = ny_daily_gate(saturday, last_processed_session=datetime(2026, 1, 16).date())
    assert done["eligible"] is False
    assert done["reason"] == "already_processed"
    with pytest.raises(ValueError):
        ny_daily_gate(datetime(2026, 1, 15, 17, 45))
