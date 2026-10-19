"""Alpaca paper submission stays off until an explicit unexpired authorization."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nomadquant.broker.paper_pilot import (
    CONNECTIVITY_PHRASE,
    ENABLE_PHRASE,
    KILL_PHRASE,
    enable_paper_orders,
    kill_paper_orders,
    paper_status,
    submit_connectivity_order,
    submit_strategy_paper_order,
)
from nomadquant.config import PAPER_API_URL
from tests.conftest import make_settings

NOW = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)


class _Asset:
    fractionable = True
    tradable = True


class _Clock:
    def __init__(self, open_: bool = True) -> None:
        self.is_open = open_
        self.timestamp = NOW


class _Account:
    def __init__(self, cash: str = "100000", buying_power: str = "400000") -> None:
        self.cash = cash
        self.equity = cash
        self.buying_power = buying_power


class _Order:
    def __init__(self, status: str = "accepted", price: str | None = None) -> None:
        self.status = status
        self.id = "broker-1"
        self.filled_avg_price = price
        self.filled_qty = None if price is None else "0.01"


class FakeClient:
    def __init__(self, *, open_: bool = True, fractionable: bool = True) -> None:
        self.clock = _Clock(open_)
        self.asset = _Asset()
        self.asset.fractionable = fractionable
        self.account = _Account()
        self.submitted: list[object] = []
        self.lookup_error: Exception | None = None
        self.submit_error: Exception | None = None
        self.record: _Order | None = _Order()

    def get_account(self) -> _Account:
        return self.account

    def get_clock(self) -> _Clock:
        return self.clock

    def get_asset(self, symbol: str) -> _Asset:
        assert symbol == "SPY"
        return self.asset

    def get_all_positions(self) -> list[object]:
        return []

    def submit_order(self, request: object) -> _Order:
        self.submitted.append(request)
        if self.submit_error:
            raise self.submit_error
        return self.record or _Order()

    def get_order_by_client_id(self, client_order_id: str) -> _Order:
        assert client_order_id
        if self.lookup_error:
            raise self.lookup_error
        if self.record is None:
            raise RuntimeError("absent")
        return self.record


def _settings(tmp_path: Path):
    return make_settings(tmp_path, paper_path=str(tmp_path / "paper.sqlite"))


def test_status_ignores_buying_power_above_the_hundred_dollar_sleeve(tmp_path: Path) -> None:
    client = FakeClient()
    report = paper_status(_settings(tmp_path), client=client, now=NOW)
    assert report["connected"] is True
    assert report["label"].startswith("ALPACA PAPER TRADING")
    assert report["sleeve_remaining_usd"] == "100"
    assert report["buying_power_ignored"] is True
    assert report["account_buying_power_usd"] == "400000"
    assert report["historical_replay_counts_as_performance"] is False
    assert report["submission_enabled"] is False
    assert report["ready_for_first_order"] is False
    assert client.submitted == []


def test_small_cash_caps_the_sleeve(tmp_path: Path) -> None:
    client = FakeClient()
    client.account = _Account(cash="40", buying_power="40")
    report = paper_status(_settings(tmp_path), client=client, now=NOW)
    assert report["sleeve_remaining_usd"] == "40"


def test_orders_stay_refused_without_authorization(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = FakeClient()
    refused = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, now=NOW
    )
    assert refused["submitted"] is False
    assert client.submitted == []
    with pytest.raises(ValueError):
        enable_paper_orders(settings, confirm="please", hours=1, now=NOW)


def test_one_open_market_connectivity_order_is_confirmed_with_the_broker(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=2, now=NOW)
    client = FakeClient()
    result = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, now=NOW
    )
    assert result["submitted"] is True
    assert result["status"] == "accepted"
    assert result["filled_avg_price"] is None
    assert result["counts_as_strategy_pnl"] is False
    assert len(client.submitted) == 1
    request = client.submitted[0]
    assert request.notional == Decimal("5")  # type: ignore[attr-defined]
    assert str(request.symbol) == "SPY"
    again = submit_connectivity_order(settings, confirm=CONNECTIVITY_PHRASE, client=client, now=NOW)
    assert again["submitted"] is False
    assert len(client.submitted) == 1


def test_closed_market_expired_auth_and_timeout_do_not_invent_a_fill(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=1, now=NOW)
    closed = FakeClient(open_=False)
    assert (
        submit_connectivity_order(settings, confirm=CONNECTIVITY_PHRASE, client=closed, now=NOW)[
            "reason"
        ]
        == "market_not_open"
    )
    assert closed.submitted == []
    expired = submit_connectivity_order(
        settings,
        confirm=CONNECTIVITY_PHRASE,
        client=FakeClient(),
        now=NOW + timedelta(hours=2),
    )
    assert expired["reason"] == "authorization_expired"
    kill_paper_orders(settings, confirm=KILL_PHRASE, now=NOW)
    assert (
        submit_connectivity_order(
            settings, confirm=CONNECTIVITY_PHRASE, client=FakeClient(), now=NOW
        )["reason"]
        == "killed"
    )
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=1, now=NOW)
    timed = FakeClient()
    timed.submit_error = TimeoutError("late")
    timed.record = None
    unknown = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=timed, now=NOW
    )
    assert unknown["status"] == "unknown"
    assert unknown["filled_avg_price"] is None
    assert (
        submit_connectivity_order(
            settings, confirm=CONNECTIVITY_PHRASE, client=FakeClient(), now=NOW
        )["submitted"]
        is False
    )


def test_strategy_order_cannot_use_buying_power_or_a_foreign_symbol(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = FakeClient()
    blocked = submit_strategy_paper_order(
        settings,
        symbol="SPY",
        side="buy",
        notional=Decimal("50"),
        risk_verdict="APPROVE",
        client=client,
        now=NOW,
    )
    assert blocked["submitted"] is False
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=1, now=NOW)
    foreign = submit_strategy_paper_order(
        settings,
        symbol="AAPL",
        side="buy",
        notional=Decimal("10"),
        risk_verdict="APPROVE",
        client=client,
        now=NOW,
    )
    assert foreign["reason"] == "symbol_or_side_refused"
    short = submit_strategy_paper_order(
        settings,
        symbol="SPY",
        side="sell",
        notional=Decimal("10"),
        risk_verdict="APPROVE",
        client=client,
        now=NOW,
    )
    assert short["reason"] == "short_selling_refused"
    huge = submit_strategy_paper_order(
        settings,
        symbol="SPY",
        side="buy",
        notional=Decimal("101"),
        risk_verdict="APPROVE",
        client=client,
        now=NOW,
    )
    assert huge["submitted"] is False
    assert client.submitted == []
    assert settings.alpaca_base_url == PAPER_API_URL
