"""Order-scoped fills, crash recovery, and the last send gate. No broker network."""

import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.broker.paper_pilot import (
    KILL_PHRASE,
    _find,
    _insert_order,
    _send,
    _update,
    kill_paper_orders,
    reconcile_paper_orders,
)
from nomadquant.daily.authorization import AUTHORIZE_PHRASE, authorize_daily_pilot
from nomadquant.daily.fills import collect_fill_pages, journal_broker_order, load_executions
from nomadquant.daily.portfolio import build_portfolio
from tests.conftest import make_settings
from tests.test_daily_pilot import WHEN
from tests.test_paper_pilot import FakeClient

MONDAY = "2024-11-04T15:00:00+00:00"
FRIDAY = "2024-11-01T21:00:00+00:00"


def test_fill_pages_keep_going_past_one_hundred_and_stop_when_a_page_fails() -> None:
    def fetch(token: str | None) -> list[dict[str, str]] | None:
        if token is None:
            return [{"id": str(index), "order_id": "broker-1"} for index in range(100)]
        if token == "99":
            return [
                {"id": "100", "order_id": "broker-1"},
                {"id": "other", "order_id": "unrelated"},
            ]
        return None

    rows = collect_fill_pages(fetch)
    assert rows is not None
    assert len(rows) == 102
    assert collect_fill_pages(lambda token: None if token else [{"id": "1"}] * 100) is None


def test_only_matching_order_fills_are_stored(tmp_path: Path) -> None:
    path = str(tmp_path / "paper.sqlite")
    local = _local("sell")
    broker = _Broker()
    activities = [
        _activity("other-fill", "someone-else", "9", "0.2"),
        _activity("fill-1", "broker-1", "11", "0.4"),
        _activity("fill-2", "broker-1", "13", "0.6"),
    ]
    assert (
        journal_broker_order(
            path,
            local,
            broker,
            activities,
            recorded_at=MONDAY,
            activity_state="complete",
        )
        == "ok"
    )
    stored = load_executions(path)
    assert [row["execution_id"] for row in stored] == ["fill-1", "fill-2"]
    assert (
        journal_broker_order(
            path,
            local,
            broker,
            activities,
            recorded_at=MONDAY,
            activity_state="complete",
        )
        == "ok"
    )
    assert len(load_executions(path)) == 2


def test_mismatched_or_incomplete_fills_are_not_written(tmp_path: Path) -> None:
    path = str(tmp_path / "paper.sqlite")
    local = _local("sell")
    broker = _Broker()
    bad_symbol = [_activity("fill-1", "broker-1", "12", "1")]
    bad_symbol[0]["symbol"] = "QQQ"
    assert (
        journal_broker_order(
            path, local, broker, bad_symbol, recorded_at=MONDAY, activity_state="complete"
        )
        == "unverified"
    )
    naive = [_activity("fill-1", "broker-1", "12", "1")]
    naive[0]["transaction_time"] = "2024-11-04T15:00:00"
    assert (
        journal_broker_order(
            path, local, broker, naive, recorded_at=MONDAY, activity_state="complete"
        )
        == "unverified"
    )
    assert (
        journal_broker_order(
            path,
            local,
            _Broker(identifier=""),
            [_activity("fill-1", "", "12", "1")],
            recorded_at=MONDAY,
            activity_state="complete",
        )
        == "unverified"
    )
    assert load_executions(path) == []
    assert (
        journal_broker_order(
            path, local, broker, None, recorded_at=MONDAY, activity_state="incomplete"
        )
        == "unverified"
    )


def test_an_aggregate_fill_is_not_assigned_to_one_session() -> None:
    orders = [
        _order("buy", "buy", "1", "10"),
        _order("sell", "sell", "1", "12"),
    ]
    executions = [
        _lot("buy", "buy", "1", "10", FRIDAY, aggregate=False),
        _lot("sell", "sell", "1", "12", MONDAY, aggregate=True),
    ]
    book = build_portfolio(
        orders,
        {"SPY": Decimal("10")},
        session=datetime.fromisoformat(MONDAY).date(),
        executions=executions,
    )
    assert book["realized_pnl_usd"] == "2"
    assert book["realized_today_usd"] is None
    assert book["accounting_state"] == "unverified"


def test_a_prepared_order_is_recovered_without_a_new_submission(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    _insert_order(
        settings.paper_path,
        client_order_id="nq-daily-crash",
        purpose="strategy",
        symbol="SPY",
        side="buy",
        notional=Decimal("25"),
        created_at=WHEN.isoformat(),
        decision_id="crash",
        counts_as_strategy_pnl=True,
    )
    client = FakeClient(when=WHEN)
    client.lookup_error = RuntimeError("absent")
    reconcile_paper_orders(settings, client=client, now=WHEN)
    assert client.submitted == []
    assert _find(settings.paper_path, "nq-daily-crash")["broker_status"] == "unknown"


def test_a_cancelled_order_can_record_a_late_partial(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    _insert_order(
        settings.paper_path,
        client_order_id="nq-daily-late",
        purpose="strategy",
        symbol="SPY",
        side="sell",
        notional=Decimal("12"),
        created_at=FRIDAY,
        decision_id="late",
        counts_as_strategy_pnl=True,
    )
    _update(
        settings.paper_path,
        "nq-daily-late",
        broker_status="canceled",
        broker_order_id="broker-1",
        filled_qty="0",
        filled_avg_price=None,
    )
    client = FakeClient(when=WHEN)
    client.record = _Late(status="canceled", filled_qty="1", price="12")
    client.fill_pages = _pages(  # type: ignore[attr-defined]
        [_activity("late-fill", "broker-1", "12", "1")]
    )
    reconcile_paper_orders(settings, client=client, now=WHEN)
    row = _find(settings.paper_path, "nq-daily-late")
    assert row["filled_qty"] == "1"
    assert row["broker_status"] == "canceled"
    assert load_executions(settings.paper_path)[0]["execution_id"] == "late-fill"
    assert client.submitted == []


def test_emergency_stop_blocks_the_send_itself(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    client_order_id = "nq-daily-etf_trend_sma_v1-2024-11-01-SPY-buy"
    _insert_order(
        settings.paper_path,
        client_order_id=client_order_id,
        purpose="strategy",
        symbol="SPY",
        side="buy",
        notional=Decimal("25"),
        created_at=WHEN.isoformat(),
        decision_id="stop",
        counts_as_strategy_pnl=True,
    )
    kill_paper_orders(settings, confirm=KILL_PHRASE, now=WHEN)
    client = FakeClient(when=WHEN)
    result = _send(settings, client, client_order_id, "SPY", "buy", Decimal("25"), now=WHEN)
    assert result["reason"] == "killed"
    assert client.submitted == []


def test_concurrent_send_and_reconcile_submit_once(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    client_order_id = "nq-daily-etf_trend_sma_v1-2024-11-01-SPY-buy"
    _insert_order(
        settings.paper_path,
        client_order_id=client_order_id,
        purpose="strategy",
        symbol="SPY",
        side="buy",
        notional=Decimal("25"),
        created_at=WHEN.isoformat(),
        decision_id="race",
        counts_as_strategy_pnl=True,
    )
    client = FakeClient(when=WHEN)
    barrier = threading.Barrier(2)

    def send() -> None:
        barrier.wait()
        _send(settings, client, client_order_id, "SPY", "buy", Decimal("25"), now=WHEN)

    def refresh() -> None:
        barrier.wait()
        reconcile_paper_orders(settings, client=client, now=WHEN)

    threads = [threading.Thread(target=send), threading.Thread(target=refresh)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(client.submitted) <= 1


class _Broker:
    def __init__(self, identifier: str = "broker-1") -> None:
        self.id = identifier
        self.status = "filled"
        self.filled_qty = "1"
        self.filled_avg_price = "12.2"
        self.symbol = "SPY"
        self.side = "sell"
        self.filled_at = MONDAY


class _Late:
    def __init__(self, status: str, filled_qty: str, price: str) -> None:
        self.id = "broker-1"
        self.status = status
        self.filled_qty = filled_qty
        self.filled_avg_price = price
        self.qty = filled_qty
        self.client_order_id = "nq-daily-late"
        self.symbol = "SPY"
        self.side = "sell"


def _local(side: str) -> dict[str, str]:
    return {
        "client_order_id": "sell",
        "purpose": "strategy",
        "symbol": "SPY",
        "side": side,
    }


def _activity(execution_id: str, order_id: str, price: str, qty: str) -> dict[str, str]:
    return {
        "id": execution_id,
        "activity_type": "FILL",
        "order_id": order_id,
        "transaction_time": MONDAY,
        "price": price,
        "qty": qty,
        "side": "sell",
        "symbol": "SPY",
    }


def _order(order_id: str, side: str, qty: str, price: str) -> dict[str, str]:
    return {
        "client_order_id": order_id,
        "purpose": "strategy",
        "broker_status": "filled",
        "side": side,
        "symbol": "SPY",
        "filled_qty": qty,
        "filled_avg_price": price,
        "notional_usd": price,
        "created_at": FRIDAY,
    }


def _lot(
    order_id: str,
    side: str,
    qty: str,
    price: str,
    executed_at: str,
    *,
    aggregate: bool,
) -> dict[str, object]:
    return {
        "execution_id": order_id,
        "client_order_id": order_id,
        "purpose": "strategy",
        "side": side,
        "symbol": "SPY",
        "qty": Decimal(qty),
        "price": Decimal(price),
        "executed_at": executed_at,
        "aggregate": aggregate,
    }


def _pages(rows: list[dict[str, str]]):
    def fill_pages(order_id: str, token: str | None) -> list[dict[str, str]]:
        assert order_id == "broker-1"
        return [] if token else rows

    return fill_pages
