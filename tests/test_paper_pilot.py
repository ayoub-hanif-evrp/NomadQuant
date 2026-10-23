"""Fake-broker regressions for the Alpaca paper sleeve. No network calls."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nomadquant.broker.paper_pilot import (  # noqa: E402
    AUTOMATIC_PHRASE,
    CONNECTIVITY_CLIENT_ID,
    CONNECTIVITY_PHRASE,
    ENABLE_PHRASE,
    KILL_PHRASE,
    enable_automatic_paper_pilot,
    enable_paper_orders,
    kill_paper_orders,
    paper_status,
    reconcile_paper_orders,
    run_automatic_paper_pilot,
    submit_connectivity_order,
    submit_strategy_paper_order,
)
from nomadquant.config import PAPER_API_URL
from tests.conftest import make_settings

NOW = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
SESSION = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)


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


class _Quotes:
    def __init__(self, when: datetime, **overrides: object) -> None:
        self.body: dict[str, object] = {
            "feed": "iex",
            "source": "alpaca_snapshot_latest_quote",
            "bid": "500.00",
            "ask": "500.02",
            "market_timestamp": when.isoformat(),
            "retrieved_at": when.isoformat(),
        }
        self.body.update(overrides)

    def latest_quote(self, symbol: str) -> dict[str, object]:
        return {**self.body, "symbol": symbol}


class _EmptyQuotes:
    def latest_quote(self, symbol: str) -> dict[str, str]:
        return {}


def _arm(tmp_path: Path, when: datetime = NOW):
    settings = _settings(tmp_path)
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=2, now=when)
    client = FakeClient(when=when)
    return settings, client


def _seed_order(
    settings,
    client: FakeClient,
    *,
    client_order_id: str,
    side: str,
    notional: str,
    status: str,
    price: str,
    filled_qty: str,
    qty: str,
) -> None:
    from nomadquant.broker.paper_pilot import _insert_order, _update

    _insert_order(
        settings.paper_path,
        client_order_id=client_order_id,
        purpose="strategy",
        symbol="SPY",
        side=side,
        notional=Decimal(notional),
        created_at=SESSION.isoformat(),
        decision_id=client_order_id,
        counts_as_strategy_pnl=False,
    )
    _update(
        settings.paper_path,
        client_order_id,
        broker_status=status,
        filled_avg_price=price,
        filled_qty=filled_qty,
        remaining_qty="0",
    )
    order = _Order(status=status, price=price, filled_qty=filled_qty, qty=qty)
    order.client_order_id = client_order_id  # type: ignore[attr-defined]
    order.symbol = "SPY"  # type: ignore[attr-defined]
    order.side = side  # type: ignore[attr-defined]
    order.notional = notional  # type: ignore[attr-defined]
    order.submitted_at = SESSION  # type: ignore[attr-defined]
    order.id = client_order_id
    client.records[client_order_id] = order
    client.broker_orders.append(order)


def _persist_intent(settings, *, signal: str, fill: str, side: str) -> None:
    from nomadquant.shadow.store import ShadowStore

    store = ShadowStore(settings.shadow_path)
    store.upsert_intent(
        intent_id=f"intent:{signal}:{side}",
        cycle_key=f"cycle:{signal}:{side}",
        state="SIGNAL_RECORDED",
        strategy_id="spy_tsmom_12_1",
        feed="sip",
        symbol="SPY",
        evidence={"side": side, "strategy_id": "spy_tsmom_12_1", "symbol": "SPY"},
        evidence_hash="test-decision",
        signal_session=signal,
        fill_session=fill,
        target_weight="1" if side == "buy" else "0",
    )


def _rising_market(tmp_path: Path, settings) -> None:
    from datetime import date

    from tests.test_pilot_month_start_lifecycle import _bars

    _bars(Path(settings.market_data_path), date(2018, 1, 2), date(2020, 2, 3))
    del tmp_path


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
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert refused["submitted"] is False
    assert client.submitted == []
    with pytest.raises(ValueError):
        enable_paper_orders(settings, confirm="please", hours=1, now=NOW)


def test_accepted_paper_order_is_not_described_as_filled(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    result = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
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
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert again["client_order_id"] == CONNECTIVITY_CLIENT_ID
    assert len(client.submitted) == 1


def test_fully_filled_paper_order_uses_the_broker_price(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.record = _Order(status="filled", price="500.10", filled_qty="0.01", qty="0.01")
    result = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
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
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
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
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert rejected["status"] == "rejected"
    assert rejected["filled_avg_price"] is None
    assert rejected["described_as_filled"] is False
    assert len(client.submitted) == 1
    again = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert len(client.submitted) == 1
    assert again["status"] == "rejected"


def test_timeout_after_submission_stays_unknown_and_blocks_a_duplicate(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.submit_error = TimeoutError("late")
    client.record = None
    unknown = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert unknown["status"] == "unknown"
    assert unknown["reason"] == "broker_record_not_confirmed"
    assert unknown["filled_avg_price"] is None
    assert unknown["status"] != "rejected"
    later = FakeClient()
    later.record = None
    blocked = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=later, quote_client=_Quotes(NOW), now=NOW
    )
    assert blocked["status"] == "unknown"
    assert later.submitted == []


def test_restart_reconciles_an_unresolved_broker_order_without_resubmitting(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.submit_error = TimeoutError("late")
    client.record = None
    submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    restart = FakeClient()
    restart.record = _Order(status="accepted")
    found = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=restart, quote_client=_Quotes(NOW), now=NOW
    )
    assert found["status"] == "accepted"
    assert found["filled_avg_price"] is None
    assert found["described_as_filled"] is False
    assert restart.submitted == []


def test_repeated_strategy_signal_uses_one_persistent_client_id(tmp_path: Path) -> None:
    when = datetime(2020, 2, 4, 15, 0, tzinfo=UTC)
    settings, client = _arm(tmp_path, when)
    _rising_market(tmp_path, settings)
    decision = "spy_tsmom_12_1:2020-02-03:SPY:buy"
    _persist_intent(settings, signal="2020-02-03", fill="2020-02-04", side="buy")
    first = submit_strategy_paper_order(
        settings, decision_id=decision, client=client, quote_client=_Quotes(when), now=when
    )
    second = submit_strategy_paper_order(
        settings, decision_id=decision, client=client, quote_client=_Quotes(when), now=when
    )
    assert first["reason"] == "retired_monthly_strategy"
    assert second["reason"] == "retired_monthly_strategy"
    assert client.submitted == []


def test_missing_or_stale_quote_blocks_before_submission(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    missing = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_EmptyQuotes(), now=NOW
    )
    stale = _Quotes(NOW, market_timestamp=(NOW - timedelta(minutes=2)).isoformat())
    old = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=stale, now=NOW
    )
    assert missing["reason"] == "missing_quote"
    assert old["reason"] == "stale_quote"
    assert client.submitted == []


def test_closed_market_and_stale_clock_block_before_submission(tmp_path: Path) -> None:
    settings, _client = _arm(tmp_path)
    closed = FakeClient(open_=False)
    assert (
        submit_connectivity_order(
            settings, confirm=CONNECTIVITY_PHRASE, client=closed, quote_client=_Quotes(NOW), now=NOW
        )["reason"]
        == "market_not_open"
    )
    stale = FakeClient()
    stale.clock.timestamp = NOW - timedelta(minutes=10)
    assert (
        submit_connectivity_order(
            settings, confirm=CONNECTIVITY_PHRASE, client=stale, quote_client=_Quotes(NOW), now=NOW
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
            quote_client=_Quotes(early),
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
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert refused["reason"] == "sleeve_exceeded"
    assert client.submitted == []


def test_buy_then_partial_sell_accounts_for_owned_shares(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path, SESSION)
    _seed_order(
        settings,
        client,
        client_order_id="buy-1",
        side="buy",
        notional="40",
        status="filled",
        price="500",
        filled_qty="0.08",
        qty="0.08",
    )
    _seed_order(
        settings,
        client,
        client_order_id="sell-1",
        side="sell",
        notional="10",
        status="partial",
        price="500",
        filled_qty="0.01",
        qty="0.02",
    )
    status = paper_status(settings, client=client, now=SESSION)
    assert Decimal(status["sleeve_remaining_usd"]) == Decimal("65")
    assert status["attributed_qty"]["SPY"] == "0.07"
    assert client.submitted == []


def test_canceled_partial_sell_does_not_overstate_shares(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path, SESSION)
    _seed_order(
        settings,
        client,
        client_order_id="buy-1",
        side="buy",
        notional="40",
        status="filled",
        price="500",
        filled_qty="0.08",
        qty="0.08",
    )
    _seed_order(
        settings,
        client,
        client_order_id="sell-1",
        side="sell",
        notional="20",
        status="canceled",
        price="500",
        filled_qty="0.03",
        qty="0.04",
    )
    status = paper_status(settings, client=client, now=SESSION)
    assert status["attributed_qty"]["SPY"] == "0.05"
    assert Decimal(status["sleeve_remaining_usd"]) == Decimal("75")


def test_authorization_expiry_and_kill_switch(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=1, now=NOW)
    expired = submit_connectivity_order(
        settings,
        confirm=CONNECTIVITY_PHRASE,
        client=FakeClient(),
        quote_client=_Quotes(NOW),
        now=NOW + timedelta(hours=2),
    )
    assert expired["reason"] == "authorization_expired"
    kill_paper_orders(settings, confirm=KILL_PHRASE, now=NOW)
    killed = submit_connectivity_order(
        settings,
        confirm=CONNECTIVITY_PHRASE,
        client=FakeClient(),
        quote_client=_Quotes(NOW),
        now=NOW,
    )
    assert killed["reason"] == "killed"
    assert killed["broker_orders"] is False


def test_fabricated_strategy_approval_cannot_submit(tmp_path: Path) -> None:
    when = datetime(2020, 2, 4, 15, 0, tzinfo=UTC)
    settings, client = _arm(tmp_path, when)
    quotes = _Quotes(when)
    qqq = submit_strategy_paper_order(
        settings,
        decision_id="spy_tsmom_12_1:2020-02-03:QQQ:buy",
        client=client,
        quote_client=quotes,
        now=when,
    )
    missing = submit_strategy_paper_order(
        settings,
        decision_id="spy_tsmom_12_1:2020-02-03:SPY:buy",
        client=client,
        quote_client=quotes,
        now=when,
    )
    future = submit_strategy_paper_order(
        settings,
        decision_id="spy_tsmom_12_1:2020-03-02:SPY:buy",
        client=client,
        quote_client=quotes,
        now=when,
    )
    same_day = datetime(2020, 2, 3, 22, 0, tzinfo=UTC)
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=4, now=same_day)
    _persist_intent(settings, signal="2020-02-03", fill="2020-02-03", side="buy")
    same = submit_strategy_paper_order(
        settings,
        decision_id="spy_tsmom_12_1:2020-02-03:SPY:buy",
        client=FakeClient(when=same_day),
        quote_client=_Quotes(same_day),
        now=same_day,
    )
    assert qqq["reason"] == "retired_monthly_strategy"
    assert missing["reason"] == "retired_monthly_strategy"
    assert same["reason"] == "retired_monthly_strategy"
    assert future["reason"] == "retired_monthly_strategy"
    assert client.submitted == []


def test_corrupt_ledger_and_broker_disagreement_fail_closed(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.record = _Order(status="filled", price="500", filled_qty="0.01", qty="0.01")
    submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    client.record.filled_qty = "0.001"
    disagreed = reconcile_paper_orders(settings, client=client, now=NOW)
    assert disagreed["blocked"] is True
    assert disagreed["reason"] == "ledger_disagreement"
    assert disagreed["sleeve_remaining_usd"] == "0"
    blocked = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
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
            corrupt,
            confirm=CONNECTIVITY_PHRASE,
            client=FakeClient(),
            quote_client=_Quotes(NOW),
            now=NOW,
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
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert report["blocked"] is True
    assert report["reason"] == "untracked_broker_order"
    assert report["sleeve_remaining_usd"] == "0"
    assert report["broker_orders"][0]["client_order_id"] == "outside-nomadquant"
    assert refused["reason"] == "untracked_broker_order"
    assert client.submitted == []


def test_reconciliation_keeps_a_growing_fill_and_the_sleeve(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    accepted = paper_status(settings, client=client, now=NOW)
    assert accepted["reason"] is None
    assert accepted["orders"][0]["broker_status"] == "accepted"
    assert Decimal(accepted["sleeve_remaining_usd"]) == Decimal("95")

    client.record.status = "partially_filled"
    client.record.filled_qty = "0.002"
    client.record.filled_avg_price = "500"
    client.record.qty = "0.01"
    unchanged = paper_status(settings, client=client, now=NOW)
    assert unchanged["orders"][0]["broker_status"] == "accepted"
    first = reconcile_paper_orders(settings, client=client, now=NOW)
    assert first["reason"] is None
    assert first["orders"][0]["broker_status"] == "partial"
    assert first["orders"][0]["filled_qty"] == "0.002"
    assert first["orders"][0]["filled_avg_price"] == "500"
    assert Decimal(first["sleeve_remaining_usd"]) == Decimal("95")

    client.record.filled_qty = "0.004"
    client.record.filled_avg_price = "501"
    larger = reconcile_paper_orders(settings, client=client, now=NOW)
    assert larger["reason"] is None
    assert larger["orders"][0]["broker_status"] == "partial"
    assert larger["orders"][0]["filled_qty"] == "0.004"
    assert larger["orders"][0]["filled_avg_price"] == "501"
    assert Decimal(larger["sleeve_remaining_usd"]) == Decimal("95")

    client.record.status = "filled"
    client.record.filled_qty = "0.01"
    client.record.filled_avg_price = "500.10"
    filled = reconcile_paper_orders(settings, client=client, now=NOW)
    assert filled["reason"] is None
    assert filled["orders"][0]["broker_status"] == "filled"
    assert filled["orders"][0]["filled_qty"] == "0.01"
    assert filled["orders"][0]["filled_avg_price"] == "500.10"
    assert Decimal(filled["sleeve_remaining_usd"]) == Decimal("94.999")
    assert len(client.submitted) == 1


class _StaleOnRecheck:
    def __init__(self) -> None:
        self.calls = 0

    def latest_quote(self, symbol: str) -> dict[str, object]:
        self.calls += 1
        quote = _Quotes(NOW).latest_quote(symbol)
        if self.calls > 1:
            quote["market_timestamp"] = (NOW - timedelta(minutes=2)).isoformat()
        return quote


def test_stale_quote_on_the_final_check_does_not_submit(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    quotes = _StaleOnRecheck()
    refused = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=quotes, now=NOW
    )
    assert refused["reason"] == "stale_quote"
    assert quotes.calls >= 2
    assert client.submitted == []


def test_fill_quantity_may_increase_and_may_not_regress(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    client.record.client_order_id = CONNECTIVITY_CLIENT_ID  # type: ignore[attr-defined]
    accepted = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert accepted["status"] == "accepted"
    client.record.status = "partially_filled"
    client.record.filled_qty = "0.004"
    client.record.filled_avg_price = "500"
    client.record.qty = "0.01"
    partial = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert partial["status"] == "partial"
    assert partial["filled_avg_price"] == "500"
    client.record.status = "filled"
    client.record.filled_qty = "0.01"
    client.record.filled_avg_price = "500.10"
    filled = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert filled["status"] == "filled"
    assert filled["filled_avg_price"] == "500.10"
    client.record.filled_qty = "0.004"
    regressed = reconcile_paper_orders(settings, client=client, now=NOW)
    assert regressed["reason"] == "ledger_disagreement"


def test_alpaca_enum_fill_status_updates_the_sleeve(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    client.record.status = "OrderStatus.FILLED"
    client.record.filled_qty = "0.006487478"
    client.record.filled_avg_price = "769.174"
    report = reconcile_paper_orders(settings, client=client, now=NOW)
    assert report["reason"] is None
    assert report["orders"][0]["broker_status"] == "filled"
    assert report["orders"][0]["filled_qty"] == "0.006487478"
    assert report["orders"][0]["filled_avg_price"] == "769.174"
    assert Decimal(report["sleeve_remaining_usd"]) == Decimal("100") - (
        Decimal("0.006487478") * Decimal("769.174")
    )


def test_quote_freshness_uses_the_receipt_clock(tmp_path: Path) -> None:
    from nomadquant.broker.paper_pilot import _quote_problem

    arrived = NOW + timedelta(seconds=3)
    quote = _Quotes(arrived).latest_quote("SPY")
    assert _quote_problem(quote, "SPY", NOW) == "future_quote"
    assert _quote_problem(quote, "SPY", arrived) is None
    settings, client = _arm(tmp_path)
    refused = submit_connectivity_order(
        settings,
        confirm=CONNECTIVITY_PHRASE,
        client=client,
        quote_client=_Quotes(arrived),
        now=NOW,
    )
    assert refused["reason"] == "future_quote"
    assert client.submitted == []


def test_future_and_inconsistent_quotes_are_rejected(tmp_path: Path) -> None:
    settings, client = _arm(tmp_path)
    future = _Quotes(NOW, market_timestamp=(NOW + timedelta(minutes=5)).isoformat())
    crossed = _Quotes(NOW, retrieved_at=(NOW - timedelta(minutes=1)).isoformat())
    invented = _Quotes(NOW, source="notebook")
    assert (
        submit_connectivity_order(
            settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=future, now=NOW
        )["reason"]
        == "future_quote"
    )
    assert (
        submit_connectivity_order(
            settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=crossed, now=NOW
        )["reason"]
        == "inconsistent_quote"
    )
    assert (
        submit_connectivity_order(
            settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=invented, now=NOW
        )["reason"]
        == "untrusted_quote"
    )
    assert client.submitted == []


class _Paged(FakeClient):
    def get_orders(self, request: object | None = None) -> list[object]:
        limit = int(getattr(request, "limit", 500) or 500)
        until = getattr(request, "until", None)
        rows = list(self.broker_orders)
        if until is not None:
            rows = [row for row in rows if row.submitted_at < until]  # type: ignore[attr-defined]
        return rows[:limit]


def test_broker_history_beyond_one_page_is_reconciled_after_a_lost_database(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    client = _Paged()
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(501):
        order = _Order(status="filled", price="1", filled_qty="1", qty="1")
        order.id = str(index)
        order.submitted_at = start + timedelta(minutes=index)  # type: ignore[attr-defined]
        order.symbol = "SPY"  # type: ignore[attr-defined]
        order.side = "buy"  # type: ignore[attr-defined]
        order.notional = "1"  # type: ignore[attr-defined]
        order.client_order_id = "nq-strategy-old-spy" if index == 0 else f"manual-{index}"  # type: ignore[attr-defined]
        rows.append(order)
    client.broker_orders = sorted(rows, key=lambda item: item.submitted_at, reverse=True)  # type: ignore[attr-defined]
    report = paper_status(settings, client=client, now=NOW)
    assert report["blocked"] is True
    assert report["reason"] == "untracked_broker_order"
    assert "nq-strategy-old-spy" in {item["client_order_id"] for item in report["broker_orders"]}
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=1, now=NOW)
    refused = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert refused["reason"] == "untracked_broker_order"
    assert client.submitted == []


def test_lost_connectivity_row_is_recovered_without_a_second_submit(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "lost")
    enable_paper_orders(settings, confirm=ENABLE_PHRASE, hours=1, now=NOW)
    client = FakeClient()
    found = _Order(status="accepted")
    found.client_order_id = CONNECTIVITY_CLIENT_ID  # type: ignore[attr-defined]
    client.records[CONNECTIVITY_CLIENT_ID] = found
    result = submit_connectivity_order(
        settings, confirm=CONNECTIVITY_PHRASE, client=client, quote_client=_Quotes(NOW), now=NOW
    )
    assert result["status"] == "accepted"
    assert result["described_as_filled"] is False
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
