"""Critical paper-path regressions. No live broker and no new authorization by default."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from nomadquant.broker.paper_pilot import _insert_order, _update
from nomadquant.daily.authorization import AUTHORIZE_PHRASE, authorize_daily_pilot
from nomadquant.daily.execute import _floor_shares, _session_limit, submit_daily_paper_order
from nomadquant.daily.fingerprint import DATASET_ID, price_fingerprint
from nomadquant.daily.influence import apply_influence
from nomadquant.daily.portfolio import build_portfolio
from nomadquant.daily.store import save_decision
from nomadquant.marketdata.calendar import sessions_between
from tests.conftest import make_settings
from tests.market_bars import seed_closes
from tests.test_daily_pilot import SIGNAL, WHEN
from tests.test_paper_pilot import FakeClient, _Quotes

TODAY = date(2024, 11, 4)


def _decision(prices: dict[str, dict[date, Decimal]], action: str) -> dict[str, object]:
    return {
        "action": action,
        "symbol": "SPY",
        "strategy_id": "etf_trend_sma_v1",
        "strategy_version": "1.0.0",
        "notional_usd": "25" if action == "BUY" else "0",
        "signal_session": SIGNAL.isoformat(),
        "execution_session": TODAY.isoformat(),
        "influence_policy": "daily_agent_influence_1.0.0",
        "risk_policy": "daily_risk_1.0.0",
        "missed_window": False,
        "market_feed": "iex",
        "market_dataset": DATASET_ID,
        "price_fingerprint": price_fingerprint(prices, feed="iex"),
    }


def _down() -> dict[str, dict[date, Decimal]]:
    sessions = sessions_between(date(2023, 12, 1), SIGNAL)
    return {
        symbol: {day: Decimal("70") if day in sessions[-5:] else Decimal("100") for day in sessions}
        for symbol in ("SPY", "QQQ")
    }


def test_daily_realized_pnl_follows_the_new_york_session() -> None:
    orders = [
        _fill("buy-y", "buy", "1", "10", "2024-11-01T15:00:00+00:00"),
        _fill("sell-y", "sell", "1", "12", "2024-11-01T16:00:00+00:00"),
        _fill("buy-t", "buy", "1", "10", "2024-11-04T15:00:00+00:00"),
        _fill("sell-t", "sell", "0.5", "8", "2024-11-04T16:00:00+00:00"),
    ]
    executions = [
        _execution(
            row["client_order_id"],
            row["side"],
            row["filled_qty"],
            row["filled_avg_price"],
            row["created_at"],
        )
        for row in orders
    ]
    book = build_portfolio(orders, {"SPY": Decimal("8")}, session=TODAY, executions=executions)
    assert book["realized_pnl_usd"] == "1.0"
    assert book["realized_today_usd"] == "-1.0"


def test_fractional_sell_floors_and_keeps_the_residual(tmp_path: Path) -> None:
    assert _floor_shares(Decimal("0.1234567899")) == Decimal("0.123456789")
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
    _open(settings, "0.1234567899", "100")
    client = FakeClient(when=WHEN)
    client.positions = [
        type("Position", (), {"symbol": "SPY", "qty": "0.1234567899", "side": "long"})()
    ]
    result = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=client,
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert result["submitted"] is True
    assert Decimal(str(client.submitted[0].qty)) == Decimal("0.123456789")  # type: ignore[attr-defined]
    assert Decimal(result["residual_qty"]) == Decimal("0.0000000009")


def test_drawdown_blocks_a_buy_and_still_allows_the_exit(tmp_path: Path) -> None:
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
    _open(settings, "1", "80")
    client = FakeClient(when=WHEN)
    client.positions = [type("Position", (), {"symbol": "SPY", "qty": "1", "side": "long"})()]
    result = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=client,
        quote_client=_Quotes(WHEN, bid="40", ask="40.02"),
        now=WHEN,
    )
    assert result["submitted"] is True
    assert Decimal(str(client.submitted[0].qty)) == Decimal("1")  # type: ignore[attr-defined]


def test_missing_and_conflicting_bars_block_submission(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    authorize_daily_pilot(settings, confirm=AUTHORIZE_PHRASE, days=1, now=WHEN)
    prices = _down()
    save_decision(
        settings.daily_path,
        created_at=WHEN.isoformat(),
        signal_session=SIGNAL.isoformat(),
        payload=_decision(prices, "SELL"),
    )
    missing = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=FakeClient(when=WHEN),
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert missing["reason"] == "unverified_market_data"
    seed_closes(settings, prices, now=WHEN)
    from nomadquant.marketdata.store import MarketStore

    store = MarketStore(settings.market_data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "UPDATE bars SET close = ? WHERE symbol = 'SPY' AND session_date = ?",
            ("1", SIGNAL.isoformat()),
        )
    conflict = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=FakeClient(when=WHEN),
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert conflict["reason"] == "authoritative_price_mismatch"


def test_future_or_untimed_bars_block_submission(tmp_path: Path) -> None:
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
    from nomadquant.marketdata.store import MarketStore

    store = MarketStore(settings.market_data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "UPDATE bars SET available_at = ? WHERE symbol = 'SPY' AND session_date = ?",
            ("2024-11-04T16:00:00+00:00", SIGNAL.isoformat()),
        )
    future = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=FakeClient(when=WHEN),
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert future["reason"] == "future_market_data"
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "UPDATE bars SET available_at = ? WHERE symbol = 'SPY' AND session_date = ?",
            ("2024-11-04T10:00:00", SIGNAL.isoformat()),
        )
    naive = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=FakeClient(when=WHEN),
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert naive["reason"] == "future_market_data"


def test_a_cancelled_partial_still_uses_the_session_limit() -> None:
    counted = {
        "purpose": "strategy",
        "broker_status": "canceled",
        "filled_qty": "0.01",
        "created_at": WHEN.isoformat(),
    }
    assert _session_limit([counted], WHEN) is True
    empty = {**counted, "filled_qty": "0"}
    assert _session_limit([empty], WHEN) is False


def test_an_unknown_order_is_not_submitted_again(tmp_path: Path) -> None:
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
    _open(settings, "1", "100")
    client_order_id = "nq-daily-etf_trend_sma_v1-2024-11-01-SPY-sell"
    _insert_order(
        settings.paper_path,
        client_order_id=client_order_id,
        purpose="strategy",
        symbol="SPY",
        side="sell",
        notional=Decimal("1"),
        created_at=WHEN.isoformat(),
        decision_id="retry",
        counts_as_strategy_pnl=True,
    )
    _update(settings.paper_path, client_order_id, broker_status="unknown")
    client = FakeClient(when=WHEN)
    client.lookup_error = RuntimeError("absent")
    result = submit_daily_paper_order(
        settings,
        decision={"action": "SELL"},
        prices=prices,
        client=client,
        quote_client=_Quotes(WHEN),
        now=WHEN,
    )
    assert result["submitted"] is False
    assert result["reason"] == "portfolio_unreconciled"
    assert client.submitted == []


def test_an_agent_cannot_invent_a_buy() -> None:
    result = apply_influence(
        {"action": "HOLD", "symbol": "SPY", "strategy_id": "etf_trend_sma_v1", "notional_usd": "0"},
        {
            "valid": True,
            "skeptic_stance": "AGREE",
            "portfolio_action": "BUY",
            "symbol": "SPY",
            "objections": [],
        },
    )
    assert result["action"] == "HOLD"


def _execution(
    order_id: str, side: str, qty: str, price: str, executed_at: str
) -> dict[str, object]:
    return {
        "execution_id": order_id,
        "client_order_id": order_id,
        "purpose": "strategy",
        "side": side,
        "symbol": "SPY",
        "qty": qty,
        "price": price,
        "executed_at": executed_at,
        "aggregate": False,
    }


def _fill(order_id: str, side: str, qty: str, price: str, created: str) -> dict[str, str]:
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


def _open(settings: object, qty: str, price: str) -> None:
    path = settings.paper_path  # type: ignore[attr-defined]
    _insert_order(
        path,
        client_order_id="nq-daily-open",
        purpose="strategy",
        symbol="SPY",
        side="buy",
        notional=Decimal(price),
        created_at="2024-11-01T15:00:00+00:00",
        decision_id="open",
        counts_as_strategy_pnl=True,
    )
    _update(path, "nq-daily-open", broker_status="filled", filled_qty=qty, filled_avg_price=price)
