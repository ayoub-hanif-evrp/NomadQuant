"""Accounting state reaches trading decisions. No broker network and no live order."""

import sqlite3
from decimal import Decimal
from pathlib import Path

from nomadquant.broker.paper_pilot import (
    _find,
    _insert_order,
    _update,
    paper_status,
    reconcile_paper_orders,
)
from nomadquant.broker.verify_account import verify_paper_account
from nomadquant.daily.authorization import AUTHORIZE_PHRASE, authorize_daily_pilot
from nomadquant.daily.cycle import daily_status
from nomadquant.daily.execute import submit_daily_paper_order
from nomadquant.daily.fills import load_executions, record_execution
from nomadquant.daily.portfolio import build_portfolio
from nomadquant.daily.store import save_decision
from tests.conftest import make_settings
from tests.market_bars import seed_closes
from tests.test_daily_pilot import WHEN, _rising
from tests.test_execution_hardening import _decision, _down, _open
from tests.test_paper_pilot import FakeClient, _Order, _Quotes

MONDAY = "2024-11-04T15:00:00+00:00"


def test_incomplete_fill_pages_stay_unverified_and_block_only_the_buy(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    _insert_order(
        settings.paper_path,
        client_order_id="nq-daily-open",
        purpose="strategy",
        symbol="SPY",
        side="buy",
        notional=Decimal("10"),
        created_at="2024-11-01T15:00:00+00:00",
        decision_id="open",
        counts_as_strategy_pnl=True,
    )
    _update(
        settings.paper_path,
        "nq-daily-open",
        broker_status="accepted",
        broker_order_id="broker-1",
        filled_qty="0",
    )
    client = FakeClient(when=WHEN)
    client.record = _Order(status="filled", price="10", filled_qty="1", qty="1")
    client.record.client_order_id = "nq-daily-open"  # type: ignore[attr-defined]
    client.record.symbol = "SPY"  # type: ignore[attr-defined]
    client.record.side = "buy"  # type: ignore[attr-defined]
    client.fill_pages = lambda _order_id, token: (  # type: ignore[attr-defined]
        [{"id": str(index), "order_id": "broker-1"} for index in range(100)]
        if token is None
        else None
    )
    reconcile_paper_orders(settings, client=client, now=WHEN)
    assert client.submitted == []
    assert load_executions(settings.paper_path) == []
    status = paper_status(settings, client=client, now=WHEN)
    assert status["accounting_state"] == "unverified"
    assert status["accounting_reason"] == "execution_history_incomplete"
    assert status["system_readiness"] == "unverified"
    assert status["reason"] is None
    assert Decimal(status["sleeve_remaining_usd"]) > 0
    desk = daily_status(settings, now=WHEN)
    assert "execution_history_incomplete" in desk["orders_blocked_reasons"]

    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    _sessions, prices = _rising()
    seed_closes(settings, prices, now=WHEN)
    save_decision(
        settings.daily_path,
        created_at=WHEN.isoformat(),
        signal_session="2024-11-01",
        payload=_decision(prices, "BUY"),
    )
    blocked = submit_daily_paper_order(
        settings,
        decision={"action": "BUY"},
        prices=prices,
        client=client,
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert blocked["reason"] == "execution_history_incomplete"
    assert client.submitted == []


def test_unverified_accounting_still_allows_a_strategy_sell(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    prices = _down()
    save_decision(
        settings.daily_path,
        created_at=WHEN.isoformat(),
        signal_session="2024-11-01",
        payload=_decision(prices, "SELL"),
    )
    seed_closes(settings, prices, now=WHEN)
    _open(settings, "1", "10")
    book = build_portfolio(
        [_find(settings.paper_path, "nq-daily-open")],
        {"SPY": Decimal("10")},
        executions=[],
    )
    assert book["accounting_state"] == "unverified"
    client = FakeClient(when=WHEN)
    client.positions = [type("Position", (), {"symbol": "SPY", "qty": "1", "side": "long"})()]
    sold = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=client,
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert sold["submitted"] is True
    assert len(client.submitted) == 1


def test_a_mismatched_journal_disputes_the_book_and_blocks_the_exit(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    _open(settings, "1", "10")
    assert (
        record_execution(
            settings.paper_path,
            {
                "execution_id": "bad-symbol",
                "client_order_id": "nq-daily-open",
                "symbol": "QQQ",
                "side": "buy",
                "qty": "1",
                "price": "10",
                "executed_at": MONDAY,
                "purpose": "strategy",
                "aggregate": False,
            },
            recorded_at=MONDAY,
        )
        == "recorded"
    )
    book = build_portfolio(
        [_find(settings.paper_path, "nq-daily-open")],
        {"SPY": Decimal("10")},
        executions=load_executions(settings.paper_path),
    )
    assert book["accounting_state"] == "disputed"
    assert book["accounting_reason"] == "journal_disagreement"
    assert book["strategy_qty"] == {}
    assert book["strategy_pnl_usd"] is None

    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    prices = _down()
    save_decision(
        settings.daily_path,
        created_at=WHEN.isoformat(),
        signal_session="2024-11-01",
        payload=_decision(prices, "SELL"),
    )
    seed_closes(settings, prices, now=WHEN)
    client = FakeClient(when=WHEN)
    refused = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=client,
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert refused["reason"] == "portfolio_disputed"
    assert client.submitted == []


def test_an_unreadable_timestamp_is_not_turned_into_a_position(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    _open(settings, "1", "10")
    with sqlite3.connect(settings.paper_path) as connection:
        connection.execute(
            """
            INSERT INTO paper_executions (
                execution_id, client_order_id, symbol, side, qty, price,
                executed_at, purpose, aggregate, recorded_at
            ) VALUES ('naive', 'nq-daily-open', 'SPY', 'buy', '1', '10',
                      '2024-11-04T15:00:00', 'strategy', 0, ?)
            """,
            (MONDAY,),
        )
    book = build_portfolio(
        [_find(settings.paper_path, "nq-daily-open")],
        {"SPY": Decimal("10")},
        executions=load_executions(settings.paper_path),
    )
    assert book["disputed"] is True
    assert book["strategy_qty"] == {}
    assert book["strategy_pnl_usd"] is None


def test_verification_reports_a_disagreement_without_rewriting_history(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = _matched_client()
    _store_match(settings)
    healthy = verify_paper_account(settings, client=client, now=WHEN)
    assert healthy["readiness"] == "healthy"
    assert healthy["broker_orders_submitted_by_this_request"] is False
    assert healthy["history_rewritten"] is False
    assert client.submitted == []

    client.record.filled_qty = "2"  # type: ignore[attr-defined]
    disagreed = verify_paper_account(settings, client=client, now=WHEN)
    assert disagreed["readiness"] == "disputed"
    assert any(item["name"] == "filled_qty_mismatch" for item in disagreed["discrepancies"])
    assert _find(settings.paper_path, "nq-daily-open")["filled_qty"] == "1"
    assert [row["execution_id"] for row in load_executions(settings.paper_path)] == ["fill-1"]
    assert client.submitted == []


def test_a_missing_journal_is_unverified_and_not_repaired(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = _matched_client()
    _store_match(settings)
    with sqlite3.connect(settings.paper_path) as connection:
        connection.execute("DELETE FROM paper_executions")
    report = verify_paper_account(settings, client=client, now=WHEN)
    assert report["readiness"] == "unverified"
    assert any(item["name"] == "journal_missing" for item in report["discrepancies"])
    assert load_executions(settings.paper_path) == []
    assert client.submitted == []


def _matched_client() -> FakeClient:
    client = FakeClient(when=WHEN)
    order = _Order(status="filled", price="10", filled_qty="1", qty="1")
    order.client_order_id = "nq-daily-open"  # type: ignore[attr-defined]
    order.symbol = "SPY"  # type: ignore[attr-defined]
    order.side = "buy"  # type: ignore[attr-defined]
    order.id = "broker-1"
    client.record = order
    client.records["nq-daily-open"] = order
    client.positions = [type("Position", (), {"symbol": "SPY", "qty": "1", "side": "long"})()]
    client.fill_pages = lambda order_id, token: (  # type: ignore[attr-defined]
        []
        if token
        else [
            {
                "id": "fill-1",
                "order_id": order_id,
                "symbol": "SPY",
                "side": "buy",
                "qty": "1",
                "price": "10",
            }
        ]
    )
    return client


def _store_match(settings: object) -> None:
    path = settings.paper_path  # type: ignore[attr-defined]
    _insert_order(
        path,
        client_order_id="nq-daily-open",
        purpose="strategy",
        symbol="SPY",
        side="buy",
        notional=Decimal("10"),
        created_at="2024-11-01T15:00:00+00:00",
        decision_id="open",
        counts_as_strategy_pnl=True,
    )
    _update(
        path,
        "nq-daily-open",
        broker_status="filled",
        broker_order_id="broker-1",
        filled_qty="1",
        filled_avg_price="10",
    )
    record_execution(
        path,
        {
            "execution_id": "fill-1",
            "client_order_id": "nq-daily-open",
            "symbol": "SPY",
            "side": "buy",
            "qty": "1",
            "price": "10",
            "executed_at": MONDAY,
            "purpose": "strategy",
            "aggregate": False,
        },
        recorded_at=MONDAY,
    )
