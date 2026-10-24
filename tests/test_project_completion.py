"""Completion evidence. No live broker, no parameter refit, and no invented corporate actions."""

import sqlite3
from decimal import Decimal
from pathlib import Path

from nomadquant.broker.paper_pilot import kill_paper_orders, reconcile_paper_orders
from nomadquant.broker.verify_account import verify_paper_account
from nomadquant.daily.ai_comparison import compare_ai_filter
from nomadquant.daily.authorization import AUTHORIZE_PHRASE, authorize_daily_pilot
from nomadquant.daily.engine import primary_candidate
from nomadquant.daily.execute import submit_daily_paper_order
from nomadquant.daily.fills import load_executions
from nomadquant.daily.portfolio import build_portfolio
from nomadquant.daily.store import save_decision
from nomadquant.marketdata.evidence import dataset_evidence
from nomadquant.research.qualification import qualify_daily_strategies
from tests.conftest import make_settings
from tests.market_bars import seed_closes
from tests.test_daily_pilot import SIGNAL, WHEN, _rising
from tests.test_execution_hardening import _decision, _down
from tests.test_paper_pilot import FakeClient, _Order, _Quotes


def test_raw_prices_are_not_a_total_return_dataset() -> None:
    evidence = dataset_evidence()
    assert evidence["adjustment"] == "raw"
    assert evidence["corporate_actions"] == "absent"
    assert evidence["split_adjusted_dataset"] is False
    assert evidence["dividend_adjusted_dataset"] is False
    assert evidence["research_state"] == "NOT_EVALUABLE"
    assert evidence["permission_to_trade"] is False
    assert evidence["feeds"] == ["iex", "sip"]


def test_registered_strategies_are_not_research_qualified() -> None:
    _sessions, prices = _rising()
    report = qualify_daily_strategies(prices, _sessions)
    assert report["state"] == "NOT_EVALUABLE"
    assert report["permission_to_trade"] is False
    assert report["parameter_refit"] is False
    assert "etf_trend_sma_v1" in report["strategies"]
    assert "etf_reversal_5d_v1" in report["strategies"]
    assert report["benchmarks"]["cash_return"] == "0"
    assert report["benchmarks"]["spy_buy_hold"] is not None
    short = qualify_daily_strategies({"SPY": {}, "QQQ": {}}, [])
    assert short["state"] == "INSUFFICIENT_DATA"


def test_a_missing_model_is_not_an_ai_improvement() -> None:
    _sessions, prices = _rising()
    report = compare_ai_filter(prices, _sessions, model_available=False)
    assert report["recommendation"] == "DETERMINISTIC_BASELINE"
    assert report["ai_incremental_benefit"] is None
    assert report["vetoes_counted"] == 0
    assert report["live_ollama_session"] is False
    assert report["measurement"] == "NOT_MEASURED"
    assert report["deterministic_buy_signals"] > 0
    supplied = compare_ai_filter(prices, _sessions, model_available=True)
    assert supplied["recommendation"] == "NOT_COMPARED"
    assert supplied["measurement"] == "NOT_MEASURED"
    assert supplied["ai_incremental_benefit"] is None


def test_paper_lifecycle_keeps_one_buy_one_exit_and_a_restart(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    _sessions, prices = _rising()
    save_decision(
        settings.daily_path,
        created_at=WHEN.isoformat(),
        signal_session=SIGNAL.isoformat(),
        payload=_decision(prices, "BUY"),
    )
    seed_closes(settings, prices, now=WHEN)
    buyer = FakeClient(when=WHEN)
    opened = submit_daily_paper_order(
        settings,
        decision={"action": "BUY"},
        prices=prices,
        client=buyer,
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert opened["submitted"] is True
    assert len(buyer.submitted) == 1
    client_order_id = str(opened["client_order_id"])
    record = _Order(status="partially_filled", price="500", filled_qty="0.05", qty="0.05")
    record.id = "broker-1"
    record.client_order_id = client_order_id  # type: ignore[attr-defined]
    record.symbol = "SPY"  # type: ignore[attr-defined]
    record.side = "buy"  # type: ignore[attr-defined]
    buyer.record = record
    buyer.records[client_order_id] = record

    def pages(order_id: str, token: str | None) -> list[dict[str, str]]:
        assert order_id == "broker-1"
        if token:
            return []
        return [
            {
                "id": "fill-1",
                "activity_type": "FILL",
                "order_id": "broker-1",
                "transaction_time": WHEN.isoformat(),
                "price": "500",
                "qty": "0.05",
                "side": "buy",
                "symbol": "SPY",
            }
        ]

    buyer.fill_pages = pages  # type: ignore[attr-defined]
    buyer.positions = [type("Position", (), {"symbol": "SPY", "qty": "0.05", "side": "long"})()]
    reconcile_paper_orders(settings, client=buyer, now=WHEN)
    assert len(buyer.submitted) == 1
    assert len(load_executions(settings.paper_path)) == 1
    book = build_portfolio(
        [
            {
                "client_order_id": client_order_id,
                "purpose": "strategy",
                "broker_status": "partial",
                "side": "buy",
                "symbol": "SPY",
                "filled_qty": "0.05",
                "filled_avg_price": "500",
                "notional_usd": "25",
                "created_at": WHEN.isoformat(),
            }
        ],
        {"SPY": Decimal("90")},
        executions=load_executions(settings.paper_path),
    )
    assert book["accounting_state"] == "verified"
    assert book["loss_stop"] is True
    checked = verify_paper_account(settings, client=buyer, now=WHEN)
    assert checked["history_rewritten"] is False
    assert checked["broker_orders_submitted_by_this_request"] is False
    assert len(buyer.submitted) == 1

    restarted = FakeClient(when=WHEN)
    restarted.record = record
    restarted.records[client_order_id] = record
    restarted.positions = buyer.positions
    again = submit_daily_paper_order(
        settings,
        decision={"action": "BUY"},
        prices=prices,
        client=restarted,
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert restarted.submitted == []
    assert again["reason"] == "fabricated_signal"

    blocked = submit_daily_paper_order(
        settings,
        decision={"action": "BUY"},
        prices=prices,
        client=buyer,
        quote_client=_Quotes(WHEN, bid="90", ask="90.02"),
        now=WHEN,
    )
    assert blocked["reason"] == "strategy_loss_stop"
    assert len(buyer.submitted) == 1
    with sqlite3.connect(settings.paper_path) as connection:
        connection.execute(
            "UPDATE paper_orders SET created_at = ? WHERE client_order_id = ?",
            ("2024-11-01T21:00:00+00:00", client_order_id),
        )

    down = _down()
    choice = primary_candidate(down, SIGNAL, {"SPY": Decimal("0.05")})
    assert choice is not None and choice["action"] == "SELL"
    with sqlite3.connect(settings.market_data_path) as connection:
        for symbol, series in down.items():
            for day, close in series.items():
                connection.execute(
                    """
                    UPDATE bars SET open = ?, high = ?, low = ?, close = ?
                    WHERE symbol = ? AND session_date = ? AND feed = 'iex'
                    """,
                    (str(close), str(close), str(close), str(close), symbol, day.isoformat()),
                )
    save_decision(
        settings.daily_path,
        created_at=WHEN.isoformat(),
        signal_session=SIGNAL.isoformat(),
        payload=_decision(down, "SELL"),
    )
    sold = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=down,
        client=buyer,
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert sold["submitted"] is True
    assert len(buyer.submitted) == 2
    assert "sell" in str(buyer.submitted[-1].side).lower()  # type: ignore[attr-defined]

    kill_paper_orders(settings, confirm="DISABLE_ALPACA_PAPER_ORDERS", now=WHEN)
    stopped = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=down,
        client=FakeClient(when=WHEN),
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert stopped["reason"] == "killed"
