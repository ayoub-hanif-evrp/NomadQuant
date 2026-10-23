"""Offline portfolio lifecycle. No broker credentials and no live order."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from nomadquant.broker.paper_pilot import (
    _insert_order,
    _update,
    paper_status,
    reconcile_paper_orders,
)
from nomadquant.daily.authorization import AUTHORIZE_PHRASE, authorize_daily_pilot
from nomadquant.daily.execute import submit_daily_paper_order
from nomadquant.daily.fingerprint import price_fingerprint
from nomadquant.daily.portfolio import build_portfolio
from nomadquant.daily.store import save_decision
from nomadquant.marketdata.calendar import sessions_between
from tests.conftest import make_settings
from tests.test_daily_pilot import SIGNAL, WHEN
from tests.test_paper_pilot import CONNECTIVITY_CLIENT_ID, FakeClient, _Quotes


def _down_spy() -> dict[str, dict[date, Decimal]]:
    sessions = sessions_between(date(2023, 12, 1), SIGNAL)
    return {
        "SPY": {day: Decimal("70") if day in sessions[-5:] else Decimal("100") for day in sessions},
        "QQQ": {day: Decimal("100") + Decimal(index) for index, day in enumerate(sessions)},
    }


def test_empty_book_starts_at_one_hundred_dollars() -> None:
    book = build_portfolio([])
    assert book["available_cash_usd"] == "100"
    assert book["equity_usd"] == "100"
    assert book["strategy_qty"] == {}
    assert book["connectivity_qty"] == "0"
    assert book["marks_complete"] is True


def test_connectivity_fill_is_not_a_strategy_holding() -> None:
    book = build_portfolio(
        [
            {
                "client_order_id": CONNECTIVITY_CLIENT_ID,
                "purpose": "connectivity",
                "broker_status": "filled",
                "side": "buy",
                "symbol": "SPY",
                "filled_qty": "0.006487478",
                "filled_avg_price": "769.174",
                "notional_usd": "5",
            }
        ],
        {"SPY": Decimal("769.174")},
    )
    cost = Decimal("0.006487478") * Decimal("769.174")
    assert book["strategy_qty"] == {}
    assert book["connectivity_qty"] == "0.006487478"
    assert book["connectivity_counts_as_strategy_pnl"] is False
    assert Decimal(book["available_cash_usd"]) == Decimal("100") - cost
    assert book["strategy_pnl_usd"] == "0"


def test_partial_buy_then_completion_is_counted_once() -> None:
    partial = {
        "client_order_id": "buy-1",
        "purpose": "strategy",
        "broker_status": "partial",
        "side": "buy",
        "symbol": "SPY",
        "filled_qty": "0.02",
        "filled_avg_price": "500",
        "notional_usd": "25",
        "created_at": "2024-11-01T15:00:00+00:00",
    }
    first = build_portfolio([partial], {"SPY": Decimal("500")})
    assert first["strategy_qty"]["SPY"] == "0.02"
    completed = {**partial, "broker_status": "filled", "filled_qty": "0.05"}
    done = build_portfolio([partial, completed], {"SPY": Decimal("500")})
    assert done["strategy_qty"]["SPY"] == "0.05"
    assert Decimal(done["available_cash_usd"]) == Decimal("75")


def test_a_price_change_does_not_increase_the_sell_quantity(tmp_path: Path) -> None:
    from nomadquant.daily.engine import primary_candidate

    settings = make_settings(tmp_path)
    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    prices = _down_spy()
    choice = primary_candidate(prices, date(2024, 11, 1), {"SPY": Decimal("0.05")})
    assert choice is not None and choice["action"] == "SELL"
    save_decision(
        settings.daily_path,
        created_at=WHEN.isoformat(),
        signal_session=SIGNAL.isoformat(),
        payload={
            "action": "SELL",
            "symbol": "SPY",
            "strategy_id": choice["strategy_id"],
            "strategy_version": choice["version"],
            "notional_usd": "0",
            "signal_session": SIGNAL.isoformat(),
            "execution_session": "2024-11-04",
            "influence_policy": "daily_agent_influence_1.0.0",
            "risk_policy": "daily_risk_1.0.0",
            "missed_window": False,
            "price_fingerprint": price_fingerprint(prices),
        },
    )
    _insert_order(
        settings.paper_path,
        client_order_id="nq-daily-open",
        purpose="strategy",
        symbol="SPY",
        side="buy",
        notional=Decimal("25"),
        created_at="2024-11-01T15:00:00+00:00",
        decision_id="open",
        counts_as_strategy_pnl=True,
    )
    _update(
        settings.paper_path,
        "nq-daily-open",
        broker_status="filled",
        filled_qty="0.05",
        filled_avg_price="500",
    )

    class _Moving:
        def __init__(self) -> None:
            self.calls = 0

        def latest_quote(self, symbol: str) -> dict[str, object]:
            self.calls += 1
            bid = "400.00" if self.calls > 2 else "500.00"
            ask = "400.02" if self.calls > 2 else "500.02"
            return _Quotes(WHEN, bid=bid, ask=ask).latest_quote(symbol)

    client = FakeClient(when=WHEN)
    client.positions = [type("Position", (), {"symbol": "SPY", "qty": "0.05", "side": "long"})()]
    result = submit_daily_paper_order(
        settings,
        decision={"action": "SELL", "strategy_id": "etf_trend_sma_v1"},
        prices=prices,
        client=client,
        quote_client=_Moving(),
        now=WHEN,
    )
    assert result["submitted"] is True
    assert Decimal(str(client.submitted[0].qty)) == Decimal("0.05")  # type: ignore[attr-defined]


def test_a_stale_mark_blocks_a_held_position(tmp_path: Path) -> None:
    from tests.test_daily_pilot import _rising

    settings = make_settings(tmp_path)
    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    _sessions, prices = _rising()
    save_decision(
        settings.daily_path,
        created_at=WHEN.isoformat(),
        signal_session=SIGNAL.isoformat(),
        payload={
            "action": "BUY",
            "symbol": "SPY",
            "strategy_id": "etf_trend_sma_v1",
            "strategy_version": "1.0.0",
            "notional_usd": "25",
            "signal_session": SIGNAL.isoformat(),
            "execution_session": "2024-11-04",
            "influence_policy": "daily_agent_influence_1.0.0",
            "risk_policy": "daily_risk_1.0.0",
            "missed_window": False,
            "price_fingerprint": price_fingerprint(prices),
        },
    )
    _insert_order(
        settings.paper_path,
        client_order_id="nq-daily-open",
        purpose="strategy",
        symbol="SPY",
        side="buy",
        notional=Decimal("25"),
        created_at="2024-11-01T15:00:00+00:00",
        decision_id="open",
        counts_as_strategy_pnl=True,
    )
    _update(
        settings.paper_path,
        "nq-daily-open",
        broker_status="filled",
        filled_qty="0.05",
        filled_avg_price="500",
    )
    refused = submit_daily_paper_order(
        settings,
        decision={"action": "BUY"},
        prices=prices,
        client=FakeClient(when=WHEN),
        quote_client=_Quotes(WHEN - timedelta(minutes=5)),
        now=WHEN,
    )
    assert refused["reason"] == "portfolio_unreconciled"
    assert refused["submitted"] is False


def test_status_read_does_not_apply_a_new_fill(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, paper_path=str(tmp_path / "paper.sqlite"))
    now = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
    _insert_order(
        settings.paper_path,
        client_order_id=CONNECTIVITY_CLIENT_ID,
        purpose="connectivity",
        symbol="SPY",
        side="buy",
        notional=Decimal("5"),
        created_at=now.isoformat(),
        decision_id=CONNECTIVITY_CLIENT_ID,
        counts_as_strategy_pnl=False,
    )
    _update(settings.paper_path, CONNECTIVITY_CLIENT_ID, broker_status="accepted")
    client = FakeClient(when=now)
    client.record.client_order_id = CONNECTIVITY_CLIENT_ID  # type: ignore[attr-defined]
    client.record.status = "filled"
    client.record.filled_qty = "0.01"
    client.record.filled_avg_price = "500"
    before = paper_status(settings, client=client, now=now)
    assert before["orders"][0]["broker_status"] == "accepted"
    after = reconcile_paper_orders(settings, client=client, now=now)
    assert after["orders"][0]["broker_status"] == "filled"
