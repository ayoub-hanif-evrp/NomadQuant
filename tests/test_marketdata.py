"""Offline daily-bar tests. No credentials and no network."""

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from nomadquant.marketdata.alpaca_bars import AlpacaDailyBars, FetchedBar
from nomadquant.marketdata.availability import (
    latest_safe_session,
    modeled_available_at,
    session_bar_timestamp,
    session_date_from_timestamp,
)
from nomadquant.marketdata.calendar import is_early_close, is_session
from nomadquant.marketdata.cli import main
from nomadquant.marketdata.errors import (
    IncompleteCoverage,
    IncompleteSession,
    InvalidBar,
    MarketDataError,
    MissingMarketData,
    SipNotEntitled,
)
from nomadquant.marketdata.provider import SqliteMarketDataProvider
from nomadquant.marketdata.report import market_data_status
from nomadquant.marketdata.store import MarketStore
from nomadquant.marketdata.sync import sync_daily_bars
from tests.conftest import make_settings

NOW = datetime(2024, 12, 31, 22, tzinfo=UTC)


def _bar(
    symbol: str = "SPY",
    session: date = date(2024, 1, 2),
    close: float = 100,
    feed: str = "sip",
    hour: int = 5,
) -> FetchedBar:
    return FetchedBar(
        symbol=symbol,
        timestamp=datetime(session.year, session.month, session.day, hour, tzinfo=UTC),
        open_=100,
        high=110,
        low=90,
        close=close,
        volume=1_000,
        feed=feed,
    )


def _sync(store: MarketStore, bars: list[FetchedBar], feed: str = "sip") -> None:
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: bars,
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 2),
        feed,
        now=NOW,
    )


def test_ohlcv_ingestion_keeps_decimal_prices(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    _sync(store, [_bar(close=100.25)])
    rows = store.bars(
        ["SPY"],
        "sip",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 3, tzinfo=UTC),
        NOW,
    )
    assert len(rows) == 1
    assert str(rows[0].close) == "100.25"
    assert rows[0].session_date == date(2024, 1, 2)
    assert rows[0].feed == "sip"
    assert rows[0].adjustment == "raw"
    assert rows[0].provider == "alpaca"
    assert rows[0].volume == 1000
    assert rows[0].available_at == datetime(2024, 1, 2, 21, 30, tzinfo=UTC)


def test_repeat_import_is_idempotent(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    bars = [_bar()]
    _sync(store, bars)
    second = sync_daily_bars(
        store,
        lambda symbols, start, end, requested: bars,
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 2),
        "sip",
        now=NOW,
    )
    assert second.counts.inserted == 0
    assert second.counts.unchanged == 1
    assert store.conflict_count() == 0


def test_revised_bar_is_kept_beside_the_original(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    _sync(store, [_bar(close=100)])
    observed = datetime(2024, 8, 2, 15, tzinfo=UTC)
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: [_bar(close=110)],
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 2),
        "sip",
        now=NOW,
        retrieved_at=lambda: observed,
    )
    stored = store.bars(
        ["SPY"],
        "sip",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 3, tzinfo=UTC),
        NOW,
    )
    assert str(stored[0].close) == "100"
    assert store.conflict_count() == 1
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: [_bar(close=110)],
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 2),
        "sip",
        now=NOW,
        retrieved_at=lambda: observed,
    )
    again = datetime(2024, 8, 3, 15, tzinfo=UTC)
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: [_bar(close=110)],
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 2),
        "sip",
        now=NOW,
        retrieved_at=lambda: again,
    )
    assert store.conflict_count() == 1
    with sqlite3.connect(tmp_path / "market.sqlite") as connection:
        row = connection.execute("SELECT COUNT(*), MIN(observed_at) FROM bar_revisions").fetchone()
    assert row is not None
    assert row[0] == 1
    assert row[1] == observed.isoformat()


def test_inconsistent_ohlc_is_rejected() -> None:
    with pytest.raises(InvalidBar):
        _bar_unchecked(low=200)
    with pytest.raises(InvalidBar):
        FetchedBar(
            symbol="SPY",
            timestamp=datetime(2024, 1, 2, 5, tzinfo=UTC),
            open_=0,
            high=1,
            low=1,
            close=1,
            volume=1,
            feed="sip",
        )


def test_same_day_close_is_hidden_before_modeled_availability(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    session = date(2024, 3, 11)
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: [_bar(session=session, hour=4)],
        ["SPY"],
        session,
        session,
        "sip",
        now=NOW,
    )
    provider = SqliteMarketDataProvider(store, "sip")
    window_start = datetime(2024, 3, 11, tzinfo=UTC)
    window_end = datetime(2024, 3, 12, tzinfo=UTC)
    hidden = provider.get_bars(
        ["SPY"], window_start, window_end, datetime(2024, 3, 11, 13, 30, tzinfo=UTC)
    )
    visible = provider.get_bars(["SPY"], window_start, window_end, modeled_available_at(session))
    assert hidden == []
    assert len(visible) == 1
    assert visible[0].session_date == session
    assert visible[0].as_of == datetime(2024, 3, 11, 20, 30, tzinfo=UTC)


def test_new_york_dates_follow_daylight_saving() -> None:
    assert session_date_from_timestamp(datetime(2024, 3, 11, 4, tzinfo=UTC)) == date(2024, 3, 11)
    assert session_date_from_timestamp(datetime(2024, 11, 4, 5, tzinfo=UTC)) == date(2024, 11, 4)
    assert modeled_available_at(date(2024, 1, 2)) == datetime(2024, 1, 2, 21, 30, tzinfo=UTC)
    assert modeled_available_at(date(2024, 3, 11)) == datetime(2024, 3, 11, 20, 30, tzinfo=UTC)


def test_holiday_is_rejected_and_early_close_is_recorded(tmp_path: Path) -> None:
    assert is_session(date(2024, 7, 4)) is False
    assert is_session(date(2024, 7, 3)) is True
    assert is_early_close(date(2024, 7, 3)) is True
    with pytest.raises(InvalidBar):
        _bar(session=date(2024, 7, 4), hour=4)
    store = MarketStore(tmp_path / "market.sqlite")
    result = sync_daily_bars(
        store,
        lambda symbols, start, end, requested: [_bar(session=date(2024, 7, 3), hour=4)],
        ["SPY"],
        date(2024, 7, 3),
        date(2024, 7, 3),
        "sip",
        now=NOW,
    )
    assert any("early-close" in warning for warning in result.warnings)


def test_sip_and_iex_stay_separate(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    _sync(store, [_bar(feed="sip")], feed="sip")
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: [_bar(feed="iex", close=90)],
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 2),
        "iex",
        now=NOW,
    )
    sip = SqliteMarketDataProvider(store, "sip")
    rows = sip.get_bars(
        ["SPY"],
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 3, tzinfo=UTC),
        NOW,
    )
    assert [row.feed for row in rows] == ["sip"]
    assert str(rows[0].close) == "100"
    with pytest.raises(MarketDataError, match="not mixed"):
        sync_daily_bars(
            store,
            lambda symbols, start, end, requested: [_bar(feed="iex")],
            ["SPY"],
            date(2024, 1, 2),
            date(2024, 1, 2),
            "sip",
            now=NOW,
        )


def test_restricted_sip_names_the_iex_retry(tmp_path: Path) -> None:
    client = AlpacaDailyBars("not-a-key", "not-a-secret", sleeper=lambda _seconds: None)
    client._client = _DeniedClient()
    with pytest.raises(SipNotEntitled, match="--feed iex"):
        client.fetch(["SPY"], date(2024, 1, 2), date(2024, 1, 2), "sip")


def test_network_failure_does_not_drop_committed_bars(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")

    def fetcher(symbols: list[str], start: date, end: date, feed: str) -> list[FetchedBar]:
        if start.year == 2018:
            return [_bar(session=date(2018, 1, 2))]
        raise MarketDataError("Alpaca market data could not be reached.")

    with pytest.raises(MarketDataError, match="could not be reached"):
        sync_daily_bars(
            store,
            fetcher,
            ["SPY"],
            date(2018, 1, 2),
            date(2019, 1, 2),
            "sip",
            now=NOW,
        )
    rows = store.bars(
        ["SPY"],
        "sip",
        datetime(2018, 1, 1, tzinfo=UTC),
        datetime(2019, 12, 31, tzinfo=UTC),
        NOW,
    )
    assert [row.session_date for row in rows] == [date(2018, 1, 2)]


def test_missing_symbol_is_not_fabricated(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    bars = [_bar(session=date(2024, 1, 2)), _bar(session=date(2024, 1, 4))]
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: bars,
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 4),
        "sip",
        now=NOW,
    )
    provider = SqliteMarketDataProvider(store, "sip")
    with pytest.raises(MissingMarketData):
        provider.get_bars(
            ["QQQ"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
            NOW,
        )
    with pytest.raises(IncompleteCoverage, match="not invented"):
        provider.get_bars(
            ["SPY"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
            NOW,
        )
    assert store.gaps("SPY", "sip") == [date(2024, 1, 3)]


def test_incomplete_session_is_not_requested(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    called = False

    def fetcher(symbols: list[str], start: date, end: date, feed: str) -> list[FetchedBar]:
        nonlocal called
        called = True
        return []

    with pytest.raises(IncompleteSession):
        sync_daily_bars(
            store,
            fetcher,
            ["SPY"],
            date(2024, 1, 2),
            date(2024, 1, 2),
            "sip",
            now=datetime(2024, 1, 2, 15, tzinfo=UTC),
        )
    assert called is False


def test_rate_limit_retries_without_leaking_the_error_body() -> None:
    sleeps: list[float] = []
    client = AlpacaDailyBars("not-a-key", "not-a-secret", sleeper=sleeps.append)
    fake = _RetryClient()
    client._client = fake
    rows = client.fetch(["SPY"], date(2024, 1, 2), date(2024, 1, 2), "sip")
    assert sleeps == [1.0, 2.0]
    assert len(rows) == 1
    assert str(rows[0].close) == "100.25"
    assert fake.saw_raw is True
    client._client = _SecretFailure()
    with pytest.raises(MarketDataError) as secret_caught:
        client.fetch(["SPY"], date(2024, 1, 2), date(2024, 1, 2), "sip")
    assert "SECRET-VALUE" not in str(secret_caught.value)


def test_report_command_stays_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(tmp_path)
    monkeypatch.setattr("nomadquant.marketdata.cli.get_settings", lambda: settings)
    main(["report", "--database", str(tmp_path / "market.sqlite")])
    captured = capsys.readouterr()
    assert "bars=0" in captured.out
    assert "suitable_for_research=False" in captured.out


def test_retrieval_time_is_not_the_job_start(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    retrieved = datetime(2024, 8, 1, 16, tzinfo=UTC)
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: [_bar()],
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 2),
        "sip",
        now=NOW,
        retrieved_at=lambda: retrieved,
    )
    rows = store.bars(
        ["SPY"],
        "sip",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 3, tzinfo=UTC),
        NOW,
    )
    assert rows[0].first_retrieved_at == retrieved
    assert rows[0].first_retrieved_at != NOW


def test_short_span_is_not_complete_for_a_longer_request(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    short = [_bar(session=date(2024, 1, day)) for day in (2, 3, 4, 5)]
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: short,
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 5),
        "sip",
        now=NOW,
    )
    narrow = market_data_status(str(store.path))
    wide = market_data_status(
        str(store.path),
        start=date(2018, 1, 2),
        end=date(2024, 1, 5),
        symbols=["SPY"],
        feed="sip",
    )
    assert narrow.coverage_complete is True
    assert narrow.suitable_for_research is True
    assert wide.suitable_for_research is False
    assert wide.coverage[0].missing_start > 0
    assert wide.coverage[0].missing_end == 0


def test_missing_edges_and_middle_are_reported(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    result = sync_daily_bars(
        store,
        lambda symbols, start, end, requested: [
            _bar(session=date(2024, 1, 2)),
            _bar(session=date(2024, 1, 4)),
        ],
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 5),
        "sip",
        now=NOW,
    )
    assert result.status == "incomplete"
    status = market_data_status(str(store.path))
    item = status.coverage[0]
    assert item.missing_start == 0
    assert item.missing_middle == 1
    assert item.missing_end == 1
    assert status.suitable_for_research is False


def test_missing_opening_sessions_are_not_hidden(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: [
            _bar(session=date(2024, 1, 4)),
            _bar(session=date(2024, 1, 5)),
        ],
        ["SPY"],
        date(2024, 1, 2),
        date(2024, 1, 5),
        "sip",
        now=NOW,
    )
    item = market_data_status(str(store.path)).coverage[0]
    assert item.missing_start == 2
    assert item.missing_middle == 0
    assert item.missing_end == 0


def test_qqq_gap_does_not_make_spy_complete_window_ready(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.sqlite")
    sync_daily_bars(
        store,
        lambda symbols, start, end, requested: [_bar(symbol="SPY")],
        ["SPY", "QQQ"],
        date(2024, 1, 2),
        date(2024, 1, 2),
        "sip",
        now=NOW,
    )
    status = market_data_status(str(store.path))
    by_symbol = {item.symbol: item for item in status.coverage}
    assert by_symbol["SPY"].gap_count == 0
    assert by_symbol["QQQ"].gap_count == 1
    assert status.suitable_for_research is False
    with pytest.raises(MissingMarketData):
        SqliteMarketDataProvider(store, "sip").get_bars(
            ["QQQ"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 3, tzinfo=UTC),
            NOW,
        )


def test_sip_request_end_stays_before_the_recent_window() -> None:
    captured: dict[str, object] = {}

    class _Capture:
        def get_stock_bars(self, request: object) -> object:
            captured["end"] = getattr(request, "end", None)
            captured["asof"] = getattr(request, "asof", None)
            return _BarSet()

    moment = datetime(2024, 3, 11, 21, tzinfo=UTC)
    client = AlpacaDailyBars("not-a-key", "not-a-secret", clock=lambda: moment)
    client._client = _Capture()
    client.fetch(["SPY"], date(2024, 3, 11), date(2024, 3, 11), "sip")
    end = captured["end"]
    assert isinstance(end, datetime)
    ceiling = (moment - timedelta(minutes=30)).replace(tzinfo=None)
    bar_time = session_bar_timestamp(date(2024, 3, 11)).replace(tzinfo=None)
    assert end <= ceiling
    assert end > bar_time
    assert end != datetime(2024, 3, 11, 23, 59, 59)
    assert captured["asof"] is None


def test_too_recent_sip_end_is_rejected_before_the_request() -> None:
    calls = {"count": 0}

    class _Counting:
        def get_stock_bars(self, request: object) -> object:
            calls["count"] += 1
            return _BarSet()

    moment = session_bar_timestamp(date(2024, 1, 2)) + timedelta(minutes=10)
    client = AlpacaDailyBars("not-a-key", "not-a-secret", clock=lambda: moment)
    client._client = _Counting()
    with pytest.raises(IncompleteSession, match="too recent"):
        client.fetch(["SPY"], date(2024, 1, 2), date(2024, 1, 2), "sip")
    assert calls["count"] == 0


def test_default_session_skips_an_open_market_day() -> None:
    opening = datetime(2024, 3, 11, 13, 30, tzinfo=UTC)
    after_close = datetime(2024, 3, 11, 21, tzinfo=UTC)
    assert latest_safe_session(opening, "sip") == date(2024, 3, 8)
    assert latest_safe_session(after_close, "sip") == date(2024, 3, 11)


def _bar_unchecked(low: float) -> FetchedBar:
    return FetchedBar(
        symbol="SPY",
        timestamp=datetime(2024, 1, 2, 5, tzinfo=UTC),
        open_=100,
        high=101,
        low=low,
        close=100,
        volume=1,
        feed="sip",
    )


class _DeniedClient:
    def get_stock_bars(self, request: object) -> object:
        raise _StatusError(403)


class _RetryClient:
    def __init__(self) -> None:
        self.calls = 0
        self.saw_raw = False

    def get_stock_bars(self, request: object) -> object:
        self.calls += 1
        feed = getattr(request, "feed", None)
        adjustment = getattr(request, "adjustment", None)
        assert getattr(feed, "value", None) == "sip"
        assert getattr(adjustment, "value", None) == "raw"
        assert getattr(request, "asof", None) is None
        self.saw_raw = True
        if self.calls < 3:
            raise _StatusError(429)
        return _BarSet()


class _SecretFailure:
    def get_stock_bars(self, request: object) -> object:
        raise _StatusError(500, "SECRET-VALUE-IN-BODY")


class _StatusError(Exception):
    def __init__(self, status_code: int, message: str = "withheld") -> None:
        super().__init__(message)
        self.status_code = status_code


class _BarSet:
    data = {
        "SPY": [
            type(
                "Bar",
                (),
                {
                    "symbol": "SPY",
                    "timestamp": datetime(2024, 1, 2, 5, tzinfo=UTC),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.25,
                    "volume": 10,
                },
            )()
        ]
    }
