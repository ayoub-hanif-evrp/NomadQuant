"""Chart bar API contracts. Uses only local fixtures — no network."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.marketdata.store import MarketStore, StoredBar, content_hash
from tests.conftest import make_settings


def _bar(session: date, close: str, symbol: str = "SPY", feed: str = "sip") -> StoredBar:
    raw = StoredBar(
        symbol=symbol,
        session_date=session,
        timestamp=datetime(session.year, session.month, session.day, 5, 0, tzinfo=UTC),
        open=Decimal(close),
        high=Decimal(close) + Decimal("1"),
        low=Decimal(close) - Decimal("1"),
        close=Decimal(close),
        volume=Decimal("1000000"),
        provider="alpaca",
        feed=feed,
        adjustment="raw",
        timeframe="1Day",
        currency="USD",
        available_at=datetime(session.year, session.month, session.day, 21, 30, tzinfo=UTC),
        first_retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
        content_hash="pending",
    )
    return StoredBar(**{**raw.__dict__, "content_hash": content_hash(raw)})


def _app(tmp_path: Path) -> TestClient:
    settings = make_settings(tmp_path)
    store = MarketStore(settings.market_data_path)
    store.write_bars(
        [
            _bar(date(2024, 1, 2), "100"),
            _bar(date(2024, 1, 3), "101"),
            _bar(date(2024, 1, 4), "102"),
            _bar(date(2024, 1, 2), "200", symbol="QQQ"),
            _bar(date(2024, 1, 2), "50", feed="iex"),
        ]
    )
    return TestClient(create_app(settings))


def test_bars_return_chronological_ohlcv_with_provenance(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        response = client.get(
            "/api/market-data/bars",
            params={"symbol": "SPY", "feed": "sip", "start": "2024-01-02", "end": "2024-01-04"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["provider"] == "alpaca"
    assert body["feed"] == "sip"
    assert body["adjustment"] == "raw"
    assert body["timeframe"] == "1Day"
    assert "Historical delayed" in body["caveat"]
    dates = [item["session_date"] for item in body["items"]]
    assert dates == ["2024-01-02", "2024-01-03", "2024-01-04"]
    first = body["items"][0]
    assert first["open"] == "100"
    assert first["high"] == "101"
    assert first["low"] == "99"
    assert first["close"] == "100"
    assert first["volume"] == "1000000"
    assert first["content_hash"]


def test_bars_do_not_mix_feeds(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        sip = client.get(
            "/api/market-data/bars",
            params={"symbol": "SPY", "feed": "sip", "start": "2024-01-02", "end": "2024-01-02"},
        ).json()
        iex = client.get(
            "/api/market-data/bars",
            params={"symbol": "SPY", "feed": "iex", "start": "2024-01-02", "end": "2024-01-02"},
        ).json()
    assert sip["total"] == 1
    assert sip["items"][0]["close"] == "100"
    assert iex["total"] == 1
    assert iex["items"][0]["close"] == "50"
    assert iex["items"][0]["feed"] == "iex"


def test_bars_reject_invalid_symbol_and_dates(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        bad_symbol = client.get(
            "/api/market-data/bars",
            params={"symbol": "AAPL", "feed": "sip", "start": "2024-01-02", "end": "2024-01-02"},
        )
        bad_range = client.get(
            "/api/market-data/bars",
            params={"symbol": "SPY", "feed": "sip", "start": "2024-01-04", "end": "2024-01-02"},
        )
        bad_feed = client.get(
            "/api/market-data/bars",
            params={"symbol": "SPY", "feed": "dark", "start": "2024-01-02", "end": "2024-01-02"},
        )
    assert bad_symbol.status_code == 400
    assert bad_range.status_code == 400
    assert bad_feed.status_code == 400


def test_bars_empty_window_and_pagination(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        empty = client.get(
            "/api/market-data/bars",
            params={"symbol": "SPY", "feed": "sip", "start": "2010-01-01", "end": "2010-01-05"},
        ).json()
        page = client.get(
            "/api/market-data/bars",
            params={
                "symbol": "SPY",
                "feed": "sip",
                "start": "2024-01-02",
                "end": "2024-01-04",
                "limit": 1,
                "offset": 1,
            },
        ).json()
    assert empty["total"] == 0
    assert empty["items"] == []
    assert page["total"] == 3
    assert len(page["items"]) == 1
    assert page["items"][0]["session_date"] == "2024-01-03"
