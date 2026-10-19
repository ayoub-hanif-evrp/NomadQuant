"""Fake-broker regressions for the Alpaca paper sleeve. No network calls."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from nomadquant.broker.paper_pilot import (
    AUTOMATIC_PHRASE,
    CONNECTIVITY_CLIENT_ID,
    CONNECTIVITY_PHRASE,
    ENABLE_PHRASE,
    KILL_PHRASE,
    enable_automatic_paper_pilot,
    enable_paper_orders,
    kill_paper_orders,
    paper_status,
    run_automatic_paper_pilot,
    submit_connectivity_order,
    submit_strategy_paper_order,
)
from nomadquant.config import PAPER_API_URL
from nomadquant.risk.policy import RiskPolicy
from tests.conftest import make_settings

NOW = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
SESSION = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
_NY = ZoneInfo("America/New_York")


class _Asset:
    fractionable = True
    tradable = True


class _Clock:
    def __init__(self, open_: bool = True, when: datetime = NOW) -> None:
        self.is_open = open_
        self.timestamp = when


class _Account:
    def __init__(self, cash: str = "100000", buying_power: str = "400000") -> None:
        self.cash = cash
        self.equity = cash
        self.buying_power = buying_power


class _Order:
    def __init__(
        self,
        status: str = "accepted",
        price: str | None = None,
        filled_qty: str | None = None,
        qty: str | None = None,
    ) -> None:
        self.status = status
        self.id = "broker-1"
        self.filled_avg_price = price
        self.filled_qty = filled_qty
        self.qty = qty


class _Position:
    def __init__(self, qty: str) -> None:
        self.symbol = "SPY"
        self.qty = qty
        self.side = "long"
        self.market_value = "40"
        self.unrealized_pl = "0"


class FakeClient:
    def __init__(self, *, open_: bool = True, when: datetime = NOW) -> None:
        self.clock = _Clock(open_, when)
        self.asset = _Asset()
        self.account = _Account()
        self.submitted: list[object] = []
        self.lookup_error: Exception | None = None
        self.submit_error: Exception | None = None
        self.record: _Order | None = _Order()
        self.records: dict[str, _Order] = {}
        self.positions: list[object] = []
        self.broker_orders: list[object] = []

    def get_account(self) -> _Account:
        return self.account

    def get_clock(self) -> _Clock:
        return self.clock

    def get_asset(self, symbol: str) -> _Asset:
        assert symbol == "SPY"
        return self.asset

    def get_all_positions(self) -> list[object]:
        return self.positions

    def get_orders(self, request: object | None = None) -> list[object]:
        assert request is not None
        return self.broker_orders

    def submit_order(self, request: object) -> _Order:
        self.submitted.append(request)
        if self.submit_error:
            raise self.submit_error
        if self.record is not None:
            client_order_id = str(getattr(request, "client_order_id", ""))
            if client_order_id:
                self.records[client_order_id] = self.record
        return self.record or _Order()

    def get_order_by_client_id(self, client_order_id: str) -> _Order:
        assert client_order_id
        if self.lookup_error:
            raise self.lookup_error
        stored = self.records.get(client_order_id)
        if stored is not None:
            return stored
        if self.record is None:
            raise RuntimeError("absent")
        return self.record


def _settings(tmp_path: Path):
    return make_settings(tmp_path, paper_path=str(tmp_path / "paper.sqlite"))


def _quote(when: datetime, *, bid: str = "500.00", ask: str = "500.02") -> dict[str, str]:
    return {
        "symbol": "SPY",
        "bid": bid,
        "ask": ask,
        "market_timestamp": when.isoformat(),
        "retrieved_at": when.isoformat(),
    }


def _evidence(when: datetime = SESSION, **overrides: object) -> dict[str, object]:
    signal = when.astimezone(_NY).date().isoformat()
    body: dict[str, object] = {
        "strategy_id": "spy_tsmom_12_1",
        "signal_session": signal,
        "execution_session": signal,
        "symbol": "SPY",
        "side": "buy",
        "notional_usd": "40",
        "risk_verdict": "APPROVE",
        "policy_hash": RiskPolicy().policy_hash(),
        "policy_version": "1.2.0",
    }
    body.update(overrides)
    body["decision_id"] = (
        f"{body['strategy_id']}:{body['signal_session']}:{body['symbol']}:{body['side']}"
    )
    return body


def _arm(tmp_path: Path, when: datetime = NOW):
    settings = _settings(tmp_path)
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=2, now=when)
    client = FakeClient(when=when)
    return settings, client


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
    assert report["quote_required_before_submit"] is True
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
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert refused["submitted"] is False
    assert client.submitted == []
    with pytest.raises(ValueError):
        enable_paper_orders(settings, confirm="please", hours=1, now=NOW)


def test_accepted_paper_order_is_not_described_as_filled(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    result = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert result["submitted"] is True
    assert result["status"] == "accepted"
    assert result["filled_avg_price"] is None
    assert result["filled_qty"] is None
    assert result["described_as_filled"] is False
    assert result["counts_as_strategy_pnl"] is False
    assert result["client_order_id"] == CONNECTIVITY_CLIENT_ID
    assert len(client.submitted) == 1
    request = client.submitted[0]
    assert request.notional == Decimal("5")  # type: ignore[attr-defined]
    assert str(request.symbol) == "SPY"
    status = paper_status(settings, client=client, now=NOW)
    assert status["sleeve_remaining_usd"] == "95"
    again = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert again["client_order_id"] == CONNECTIVITY_CLIENT_ID
    assert len(client.submitted) == 1


def test_fully_filled_paper_order_uses_the_broker_price(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.record = _Order(status="filled", price="500.10", filled_qty="0.01", qty="0.01")
    result = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert result["status"] == "filled"
    assert result["filled_qty"] == "0.01"
    assert result["remaining_qty"] == "0.00"
    assert result["filled_avg_price"] == "500.10"
    assert result["described_as_filled"] is True
    status = paper_status(settings, client=client, now=NOW)
    assert Decimal(status["sleeve_remaining_usd"]) == Decimal("94.999")


def test_partial_fill_stays_partial(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.record = _Order(status="partially_filled", price="500", filled_qty="0.004", qty="0.01")
    result = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert result["status"] == "partial"
    assert result["described_as_filled"] is False
    assert result["filled_qty"] == "0.004"
    assert result["remaining_qty"] == "0.006"
    assert result["filled_avg_price"] == "500"
    assert result["status"] != "filled"


def test_broker_rejection_is_used_only_when_the_record_says_so(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.submit_error = RuntimeError("http 422")
    client.record = _Order(status="rejected")
    rejected = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert rejected["status"] == "rejected"
    assert rejected["filled_avg_price"] is None
    assert rejected["described_as_filled"] is False
    assert len(client.submitted) == 1
    again = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert len(client.submitted) == 1
    assert again["status"] == "rejected"


def test_timeout_after_submission_stays_unknown_and_blocks_a_duplicate(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.submit_error = TimeoutError("late")
    client.record = None
    unknown = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert unknown["status"] == "unknown"
    assert unknown["reason"] == "broker_record_not_confirmed"
    assert unknown["filled_avg_price"] is None
    assert unknown["status"] != "rejected"
    later = FakeClient()
    later.record = None
    blocked = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=later, quote=_quote(NOW), now=NOW
    )
    assert blocked["status"] == "unknown"
    assert later.submitted == []


def test_restart_reconciles_an_unresolved_broker_order_without_resubmitting(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.submit_error = TimeoutError("late")
    client.record = None
    submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    restart = FakeClient()
    restart.record = _Order(status="accepted")
    found = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=restart, quote=_quote(NOW), now=NOW
    )
    assert found["status"] == "accepted"
    assert found["filled_avg_price"] is None
    assert found["described_as_filled"] is False
    assert restart.submitted == []


def test_repeated_strategy_signal_uses_one_persistent_client_id(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path, SESSION)
    evidence = _evidence()
    first = submit_strategy_paper_order(
        settings, evidence=evidence, client=client, quote=_quote(SESSION), now=SESSION
    )
    second = submit_strategy_paper_order(
        settings, evidence=evidence, client=client, quote=_quote(SESSION), now=SESSION
    )
    assert first["status"] == "accepted"
    assert first["client_order_id"] == second["client_order_id"]
    assert first["client_order_id"] == "nq-strategy-spy_tsmom_12_1-2026-10-01-SPY-buy"
    assert len(client.submitted) == 1
    assert first["counts_as_strategy_pnl"] is True


def test_missing_or_stale_quote_blocks_before_submission(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    missing = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=None, now=NOW
    )
    stale = _quote(NOW)
    stale["market_timestamp"] = (NOW - timedelta(minutes=2)).isoformat()
    old = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=stale, now=NOW
    )
    assert missing["reason"] == "missing_quote"
    assert old["reason"] == "stale_quote"
    assert client.submitted == []


def test_closed_market_and_stale_clock_block_before_submission(tmp_path: Path) -> None:
    settings, _client = _arm(tmp_path)
    closed = FakeClient(open_=False)
    assert (
        submit_connectivity_order(
            settings, confirm=CONNECTIVITY_PHRASE, client=closed, quote=_quote(NOW), now=NOW
        )["reason"]
        == "market_not_open"
    )
    stale = FakeClient()
    stale.clock.timestamp = NOW - timedelta(minutes=10)
    assert (
        submit_connectivity_order(
            settings, confirm=CONNECTIVITY_PHRASE, client=stale, quote=_quote(NOW), now=NOW
        )["reason"]
        == "stale_clock"
    )
    early = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    before_open = FakeClient(when=early)
    assert (
        submit_connectivity_order(
            settings,
            confirm=CONNECTIVITY_PHRASE,
            client=before_open,
            quote=_quote(early),
            now=early,
        )["reason"]
        == "outside_regular_hours"
    )
    assert closed.submitted == []
    assert stale.submitted == []
    assert before_open.submitted == []


def test_insufficient_sleeve_ignores_paper_buying_power(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.account = _Account(cash="4", buying_power="400000")
    refused = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert refused["reason"] == "sleeve_exceeded"
    assert client.submitted == []


def test_buy_then_partial_sell_accounts_for_owned_shares(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path, SESSION)
    client.record = _Order(status="filled", price="500", filled_qty="0.08", qty="0.08")
    bought = submit_strategy_paper_order(
        settings,
        evidence=_evidence(notional_usd="40"),
        client=client,
        quote=_quote(SESSION),
        now=SESSION,
    )
    assert bought["status"] == "filled"
    client.positions = [_Position("0.08")]
    client.record = _Order(status="partially_filled", price="500", filled_qty="0.01", qty="0.02")
    sold = submit_strategy_paper_order(
        settings,
        evidence=_evidence(side="sell", notional_usd="10"),
        client=client,
        quote=_quote(SESSION),
        now=SESSION,
    )
    assert sold["status"] == "partial"
    assert sold["described_as_filled"] is False
    assert sold["filled_qty"] == "0.01"
    status = paper_status(settings, client=client, now=SESSION)
    assert Decimal(status["sleeve_remaining_usd"]) == Decimal("65")
    assert status["attributed_qty"]["SPY"] == "0.07"
    assert len(client.submitted) == 2


def test_sell_cannot_exceed_attributed_holdings(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path, SESSION)
    client.record = _Order(status="filled", price="500", filled_qty="0.08", qty="0.08")
    submit_strategy_paper_order(
        settings,
        evidence=_evidence(notional_usd="40"),
        client=client,
        quote=_quote(SESSION),
        now=SESSION,
    )
    client.positions = [_Position("0.08")]
    refused = submit_strategy_paper_order(
        settings,
        evidence=_evidence(side="sell", notional_usd="41"),
        client=client,
        quote=_quote(SESSION),
        now=SESSION,
    )
    flat = submit_strategy_paper_order(
        settings,
        evidence=_evidence(side="sell", notional_usd="10"),
        client=FakeClient(when=SESSION),
        quote=_quote(SESSION),
        now=SESSION,
    )
    assert refused["reason"] == "sell_exceeds_holdings"
    assert flat["reason"] == "holdings_unconfirmed"
    assert len(client.submitted) == 1


def test_authorization_expiry_and_kill_switch(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=1, now=NOW)
    expired = submit_connectivity_order(
        settings,
        confirm=CONNECTIVITY_PHRASE,
        client=FakeClient(),
        quote=_quote(NOW),
        now=NOW + timedelta(hours=2),
    )
    assert expired["reason"] == "authorization_expired"
    kill_paper_orders(settings, confirm=KILL_PHRASE, now=NOW)
    killed = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=FakeClient(), quote=_quote(NOW), now=NOW
    )
    assert killed["reason"] == "killed"
    assert killed["broker_orders"] is False


def test_fabricated_strategy_approval_cannot_submit(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path, SESSION)
    fabricated = submit_strategy_paper_order(
        settings,
        evidence={"risk_verdict": "APPROVE"},
        client=client,
        quote=_quote(SESSION),
        now=SESSION,
    )
    wrong_hash = _evidence(policy_hash="not-the-policy")
    forged = submit_strategy_paper_order(
        settings, evidence=wrong_hash, client=client, quote=_quote(SESSION), now=SESSION
    )
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=2, now=NOW)
    wrong_day = submit_strategy_paper_order(
        settings, evidence=_evidence(NOW), client=client, quote=_quote(NOW), now=NOW
    )
    assert fabricated["reason"] == "untrusted_strategy_approval"
    assert forged["reason"] == "untrusted_strategy_approval"
    assert wrong_day["reason"] == "ineligible_session"
    assert client.submitted == []


def test_corrupt_ledger_and_broker_disagreement_fail_closed(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.record = _Order(status="filled", price="500", filled_qty="0.01", qty="0.01")
    submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    client.record.filled_qty = "9"
    disagreed = paper_status(settings, client=client, now=NOW)
    assert disagreed["blocked"] is True
    assert disagreed["reason"] == "ledger_disagreement"
    assert disagreed["sleeve_remaining_usd"] == "0"
    blocked = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert blocked["submitted"] is False
    assert len(client.submitted) == 1
    corrupt = _settings(tmp_path / "other")
    ledger = Path(corrupt.paper_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("this is not sqlite", encoding="utf-8")
    assert paper_status(corrupt, client=FakeClient(), now=NOW)["reason"] == "ledger_unreadable"
    assert (
        submit_connectivity_order(
            corrupt, confirm=CONNECTIVITY_PHRASE, client=FakeClient(), quote=_quote(NOW), now=NOW
        )["reason"]
        == "ledger_unreadable"
    )


def test_untracked_broker_order_fails_closed(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    foreign = _Order(status="accepted")
    foreign.client_order_id = "outside-nomadquant"  # type: ignore[attr-defined]
    foreign.symbol = "SPY"  # type: ignore[attr-defined]
    foreign.side = "buy"  # type: ignore[attr-defined]
    foreign.notional = "10"  # type: ignore[attr-defined]
    client.broker_orders = [foreign]
    report = paper_status(settings, client=client, now=NOW)
    refused = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote=_quote(NOW), now=NOW
    )
    assert report["blocked"] is True
    assert report["reason"] == "untracked_broker_order"
    assert report["sleeve_remaining_usd"] == "0"
    assert report["broker_orders"][0]["client_order_id"] == "outside-nomadquant"
    assert refused["reason"] == "untracked_broker_order"
    assert client.submitted == []


def test_automatic_pilot_is_prepared_and_does_not_submit(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path, SESSION)
    idle = run_automatic_paper_pilot(settings, client=client, now=SESSION)
    assert idle["submitted"] is False
    assert idle["reason"] == "automatic_pilot_disabled"
    assert idle["schedule_installed"] is False
    with pytest.raises(ValueError):
        enable_automatic_paper_pilot(settings, confirm="go", hours=1, now=SESSION)
    armed = enable_automatic_paper_pilot(settings, confirm=AUTOMATIC_PHRASE, hours=2, now=SESSION)
    assert armed["orders_sent"] == 0
    quiet = run_automatic_paper_pilot(settings, client=client, now=SESSION)
    assert quiet["submitted"] is False
    assert quiet["reason"] == "no_eligible_monthly_signal"
    assert client.submitted == []
    assert settings.alpaca_base_url == PAPER_API_URL
