"""Execution-level accounting. Fake fills only; no broker connection."""

import threading
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.broker.paper_pilot import _insert_order
from nomadquant.daily.authorization import AUTHORIZE_PHRASE, authorize_daily_pilot
from nomadquant.daily.fills import (
    execution_from_activity,
    execution_from_trade_update,
    load_executions,
    record_execution,
)
from nomadquant.daily.fingerprint import authoritative_disagreement, price_fingerprint
from nomadquant.daily.portfolio import build_portfolio
from nomadquant.daily.store import save_decision
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore
from tests.conftest import make_settings
from tests.market_bars import seed_closes
from tests.test_daily_pilot import SIGNAL, WHEN
from tests.test_execution_hardening import _decision, _down
from tests.test_paper_pilot import FakeClient, _Quotes

MONDAY = date(2024, 11, 4)
FRIDAY = "2024-11-01T21:00:00+00:00"
MONDAY_FILL = "2024-11-04T15:00:00+00:00"


def test_a_friday_order_filled_monday_counts_on_monday() -> None:
    orders = [
        _order("buy", "buy", "1", "10", FRIDAY),
        _order("sell", "sell", "1", "12", FRIDAY),
    ]
    executions = [
        _lot("buy", "buy", "1", "10", FRIDAY),
        _lot("sell", "sell", "1", "12", MONDAY_FILL),
    ]
    book = build_portfolio(orders, {"SPY": Decimal("10")}, session=MONDAY, executions=executions)
    assert book["realized_pnl_usd"] == "2"
    assert book["realized_today_usd"] == "2"


def test_partial_fills_are_recorded_once_and_survive_replay(tmp_path: Path) -> None:
    path = str(tmp_path / "paper.sqlite")
    first = _lot("buy", "buy", "1", "10", FRIDAY, execution_id="fill-1")
    second = _lot("sell", "sell", "0.4", "11", MONDAY_FILL, execution_id="fill-2")
    third = _lot("sell", "sell", "0.6", "13", MONDAY_FILL, execution_id="fill-3")
    for execution in (first, second, third):
        assert record_execution(path, execution, recorded_at=MONDAY_FILL) == "recorded"
        assert record_execution(path, execution, recorded_at=MONDAY_FILL) == "duplicate"
    changed = {**second, "price": Decimal("99")}
    assert record_execution(path, changed, recorded_at=MONDAY_FILL) == "conflict"
    stored = load_executions(path)
    orders = [
        _order("buy", "buy", "1", "10", FRIDAY),
        _order("sell", "sell", "1", "12.2", FRIDAY),
    ]
    before = build_portfolio(orders, {"SPY": Decimal("1")}, session=MONDAY, executions=stored)
    after = build_portfolio(
        orders, {"SPY": Decimal("1")}, session=MONDAY, executions=load_executions(path)
    )
    assert before == after
    assert before["strategy_qty"] == {}
    assert Decimal(str(before["realized_today_usd"])) == Decimal("2.2")
    assert len(stored) == 3


def test_a_cancelled_partial_keeps_the_executed_shares() -> None:
    orders = [
        _order("buy", "buy", "1", "10", FRIDAY),
        {**_order("sell", "sell", "0.25", "12", FRIDAY), "broker_status": "canceled"},
    ]
    executions = [
        _lot("buy", "buy", "1", "10", FRIDAY),
        _lot("sell", "sell", "0.25", "12", MONDAY_FILL),
    ]
    book = build_portfolio(orders, {"SPY": Decimal("12")}, session=MONDAY, executions=executions)
    assert book["strategy_qty"] == {"SPY": "0.75"}
    assert Decimal(str(book["realized_today_usd"])) == Decimal("0.5")
    assert book["reserved_sell_qty"] == {}


def test_a_sell_without_an_execution_time_is_not_assigned_to_today() -> None:
    orders = [
        _order("buy", "buy", "1", "10", FRIDAY),
        _order("sell", "sell", "1", "12", FRIDAY),
    ]
    book = build_portfolio(orders, {"SPY": Decimal("10")}, session=MONDAY)
    assert book["realized_pnl_usd"] == "2"
    assert book["realized_today_usd"] is None


def test_two_holdings_can_exit_and_a_missing_mark_blocks(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    prices = _down()
    save_decision(
        settings.daily_path,
        created_at=WHEN.isoformat(),
        signal_session=SIGNAL.isoformat(),
        payload=_decision(prices, "SELL"),
    )
    seed_closes(settings, prices, now=WHEN)
    _insert_order(
        settings.paper_path,
        client_order_id="open-spy",
        purpose="strategy",
        symbol="SPY",
        side="buy",
        notional=Decimal("10"),
        created_at=FRIDAY,
        decision_id="open-spy",
        counts_as_strategy_pnl=True,
    )
    _insert_order(
        settings.paper_path,
        client_order_id="open-qqq",
        purpose="strategy",
        symbol="QQQ",
        side="buy",
        notional=Decimal("10"),
        created_at=FRIDAY,
        decision_id="open-qqq",
        counts_as_strategy_pnl=True,
    )
    from nomadquant.broker.paper_pilot import _update

    for client_order_id in ("open-spy", "open-qqq"):
        _update(
            settings.paper_path,
            client_order_id,
            broker_status="filled",
            filled_qty="0.1",
            filled_avg_price="100",
        )
    client = FakeClient(when=WHEN)
    client.positions = [
        type("Position", (), {"symbol": "SPY", "qty": "0.2", "side": "long"})(),
        type("Position", (), {"symbol": "QQQ", "qty": "0.1", "side": "long"})(),
    ]
    from nomadquant.daily.execute import submit_daily_paper_order

    blocked = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=client,
        quote_client=_OneQuote(WHEN),
        now=WHEN,
    )
    assert blocked["reason"] == "portfolio_unreconciled"
    assert client.submitted == []
    result = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=client,
        quote_client=_Quotes(WHEN, bid="90", ask="90.02"),
        now=WHEN,
    )
    assert result["submitted"] is True
    assert client.submitted[0].symbol == "SPY"  # type: ignore[attr-defined]


def test_iex_and_sip_can_coexist_when_the_decision_names_iex(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    prices = _down()
    seed_closes(settings, prices, now=WHEN, feed="iex")
    seed_closes(settings, prices, now=WHEN, feed="sip")
    store = MarketStore(settings.market_data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "UPDATE bars SET close = ? WHERE symbol = 'SPY' AND feed = 'sip'",
            ("1",),
        )
    assert (
        authoritative_disagreement(settings, prices, feed="iex", decided_at=WHEN, now=WHEN) is None
    )
    assert price_fingerprint(prices, feed="iex") != price_fingerprint(prices, feed="sip")


def test_a_bar_published_after_the_decision_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    prices = _down()
    later = datetime(2024, 11, 4, 18, 0, tzinfo=UTC)
    seed_closes(settings, prices, now=later)
    reason = authoritative_disagreement(settings, prices, feed="iex", decided_at=WHEN, now=later)
    assert reason == "unavailable_at_decision"


def test_repeated_requests_submit_one_order(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    sessions = sessions_between(date(2023, 12, 1), SIGNAL)
    prices = {
        symbol: {day: Decimal(100 + index) for index, day in enumerate(sessions)}
        for symbol in ("SPY", "QQQ")
    }
    save_decision(
        settings.daily_path,
        created_at=WHEN.isoformat(),
        signal_session=SIGNAL.isoformat(),
        payload={**_decision(prices, "BUY"), "notional_usd": "25"},
    )
    seed_closes(settings, prices, now=WHEN)
    client = FakeClient(when=WHEN)
    barrier = threading.Barrier(2)
    results: list[dict[str, object]] = []

    def once() -> None:
        from nomadquant.daily.execute import submit_daily_paper_order

        barrier.wait()
        results.append(
            submit_daily_paper_order(
                settings,
                decision={"action": "BUY"},
                prices=prices,
                client=client,
                quote_client=_Quotes(WHEN),
                now=WHEN,
            )
        )

    threads = [threading.Thread(target=once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(client.submitted) == 1


def test_activity_and_trade_update_need_a_stable_id() -> None:
    activity = execution_from_activity(
        {
            "id": "202411040000",
            "activity_type": "FILL",
            "transaction_time": MONDAY_FILL,
            "price": "12",
            "qty": "0.5",
            "side": "sell",
            "symbol": "SPY",
            "order_id": "broker-1",
        },
        client_order_id="sell",
        purpose="strategy",
    )
    assert activity is not None
    assert activity["executed_at"] == MONDAY_FILL
    assert (
        execution_from_trade_update(
            {
                "event": "partial_fill",
                "timestamp": MONDAY_FILL,
                "qty": "0.5",
                "price": "12",
                "order": {},
            },
            purpose="strategy",
        )
        is None
    )


def _order(order_id: str, side: str, qty: str, price: str, created: str) -> dict[str, str]:
    return {
        "client_order_id": order_id,
        "purpose": "strategy",
        "broker_status": "filled",
        "side": side,
        "symbol": "SPY",
        "filled_qty": qty,
        "filled_avg_price": price,
        "notional_usd": price,
        "created_at": created,
    }


def _lot(
    order_id: str,
    side: str,
    qty: str,
    price: str,
    executed_at: str,
    *,
    execution_id: str | None = None,
) -> dict[str, object]:
    return {
        "execution_id": execution_id or order_id,
        "client_order_id": order_id,
        "purpose": "strategy",
        "side": side,
        "symbol": "SPY",
        "qty": Decimal(qty),
        "price": Decimal(price),
        "executed_at": executed_at,
        "aggregate": False,
    }


class _OneQuote:
    def __init__(self, when: datetime) -> None:
        self.when = when

    def latest_quote(self, symbol: str) -> dict[str, object]:
        if symbol == "QQQ":
            return {}
        return _Quotes(self.when).latest_quote(symbol)
