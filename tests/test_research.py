"""Offline research engine tests. No network and no credentials."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.audit import AuditLog
from nomadquant.config import Settings
from nomadquant.marketdata.calendar import next_session, sessions_between
from nomadquant.marketdata.store import MarketStore, StoredBar, content_hash
from nomadquant.research.engine import DailyBacktestEngine, IncompleteResearchData, SessionBar
from nomadquant.research.metrics import compute_metrics
from nomadquant.research.models import CostModel, EquityPoint, ExperimentConfig, WindowSpec
from nomadquant.research.portfolio import Portfolio
from nomadquant.research.replay import replay_run
from nomadquant.research.runner import run_experiment
from nomadquant.research.signals import momentum_return, target_from_momentum


def _bar(session: date, open_: str, close: str) -> SessionBar:
    open_px = Decimal(open_)
    close_px = Decimal(close)
    return SessionBar(
        session_date=session,
        open=open_px,
        high=max(open_px, close_px),
        low=min(open_px, close_px),
        close=close_px,
    )


def _config(**overrides: object) -> ExperimentConfig:
    values: dict[str, object] = {
        "experiment_id": "toy-tsmom",
        "hypothesis_id": "H-TOY",
        "title": "Toy",
        "description": "Toy fixture",
        "citations": [],
        "symbols": ["SPY"],
        "feed": "sip",
        "adjustment": "raw",
        "research_mode": "price_only",
        "data_start": date(2020, 1, 2),
        "data_end": date(2020, 6, 30),
        "evaluation_start": date(2020, 3, 2),
        "evaluation_end": date(2020, 6, 30),
        "windows": WindowSpec(
            train_start=date(2020, 3, 2),
            train_end=date(2020, 4, 30),
            validation_start=date(2020, 5, 1),
            validation_end=date(2020, 5, 29),
            test_start=date(2020, 6, 1),
            test_end=date(2020, 6, 30),
        ),
        "strategy_id": "spy_tsmom_12_1",
        "lookback_sessions": 5,
        "skip_sessions": 1,
        "initial_capital_usd": Decimal("100"),
        "costs": CostModel(
            commission_usd=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            min_notional_usd=Decimal("1"),
        ),
        "caveats": ["price-only"],
    }
    values.update(overrides)
    return ExperimentConfig.model_validate(values)


def _fill_market(path: Path, sessions: list[date], closes: list[str]) -> None:
    store = MarketStore(path)
    bars: list[StoredBar] = []
    for session, close in zip(sessions, closes, strict=True):
        raw = StoredBar(
            symbol="SPY",
            session_date=session,
            timestamp=datetime(session.year, session.month, session.day, 4, 0, tzinfo=UTC),
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            volume=Decimal("1000"),
            provider="alpaca",
            feed="sip",
            adjustment="raw",
            timeframe="1Day",
            currency="USD",
            available_at=datetime(session.year, session.month, session.day, 20, 30, tzinfo=UTC),
            first_retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
            content_hash="pending",
        )
        bars.append(StoredBar(**{**raw.__dict__, "content_hash": content_hash(raw)}))
    store.write_bars(bars)


def test_no_same_day_close_execution_for_close_signal() -> None:
    sessions = sessions_between(date(2020, 1, 2), date(2020, 4, 30))
    bars = {
        session: _bar(session, "100", "100" if index < 10 else str(100 + index))
        for index, session in enumerate(sessions)
    }
    config = _config(
        data_start=sessions[0],
        data_end=sessions[-1],
        evaluation_start=sessions[20],
        evaluation_end=sessions[-1],
        lookback_sessions=5,
        skip_sessions=0,
    )
    result = DailyBacktestEngine().run_experiment_strategy(
        strategy_id="spy_tsmom_12_1",
        config=config,
        bars=bars,
        lookback=5,
        skip=0,
        mode="momentum",
    )
    for decision in result.decisions:
        if decision.signal != "tsmom_rebalance":
            continue
        assert decision.fill_session is not None
        assert decision.fill_session > decision.session_date
        assert decision.fill_session == next_session(decision.session_date)


def test_cash_never_negative_and_no_shorts() -> None:
    portfolio = Portfolio(
        cash=Decimal("100"),
        costs=CostModel(spread_bps=Decimal("0"), slippage_bps=Decimal("0")),
    )
    trade = portfolio.rebalance_to_weight(
        symbol="SPY",
        target_weight=Decimal("1"),
        price=Decimal("50"),
        session_date=date(2020, 1, 2),
        reason="buy",
    )
    assert trade is not None
    assert portfolio.cash >= 0
    assert portfolio.quantity("SPY") > 0
    sell = portfolio.rebalance_to_weight(
        symbol="SPY",
        target_weight=Decimal("0"),
        price=Decimal("50"),
        session_date=date(2020, 1, 3),
        reason="sell",
    )
    assert sell is not None
    assert portfolio.cash >= 0
    assert portfolio.quantity("SPY") == 0


def test_fractional_shares_respect_budget() -> None:
    portfolio = Portfolio(
        cash=Decimal("100"),
        costs=CostModel(spread_bps=Decimal("0"), slippage_bps=Decimal("0")),
    )
    trade = portfolio.rebalance_to_weight(
        symbol="SPY",
        target_weight=Decimal("1"),
        price=Decimal("333.33"),
        session_date=date(2020, 1, 2),
        reason="buy",
    )
    assert trade is not None
    assert trade.quantity * trade.price <= Decimal("100")
    assert portfolio.cash >= 0


def test_missing_data_rejects_experiment() -> None:
    sessions = sessions_between(date(2020, 1, 2), date(2020, 2, 28))
    bars = {session: _bar(session, "100", "101") for session in sessions[:-3]}
    config = _config(data_start=sessions[0], data_end=sessions[-1], evaluation_start=sessions[5])
    try:
        DailyBacktestEngine().run_experiment_strategy(
            strategy_id="x",
            config=config,
            bars=bars,
            lookback=2,
            skip=0,
            mode="momentum",
        )
        raise AssertionError("expected IncompleteResearchData")
    except IncompleteResearchData as exc:
        assert "Missing" in str(exc)


def test_undefined_sharpe_is_null() -> None:
    metrics = compute_metrics(
        window="test",
        equity=[
            EquityPoint(
                session_date=date(2020, 1, 2),
                equity=Decimal("100"),
                cash=Decimal("100"),
                exposure=Decimal("0"),
                drawdown=Decimal("0"),
                window="test",
            )
        ],
        trades=[],
        start_capital=Decimal("100"),
    )
    assert metrics.sharpe is None
    assert "sharpe" in metrics.unavailable


def test_reproducible_momentum_signal() -> None:
    sessions = sessions_between(date(2020, 1, 2), date(2020, 3, 31))
    closes = {session: Decimal(100 + index) for index, session in enumerate(sessions)}
    as_of = sessions[30]
    first = momentum_return(closes, sessions, as_of, 10, 1)
    second = momentum_return(closes, sessions, as_of, 10, 1)
    assert first == second
    assert target_from_momentum(first) in {Decimal("0"), Decimal("1")}


def test_experiment_persists_and_replay_matches(tmp_path: Path) -> None:
    sessions = sessions_between(date(2019, 1, 2), date(2020, 6, 30))
    closes = [str(100 + (index % 7)) for index in range(len(sessions))]
    market = tmp_path / "market.sqlite"
    _fill_market(market, sessions, closes)
    settings = Settings(
        _env_file=None,
        database_path=str(tmp_path / "nomadquant.db"),
        market_data_path=str(market),
        research_path=str(tmp_path / "research.sqlite"),
    )
    config = _config(
        data_start=sessions[0],
        data_end=sessions[-1],
        evaluation_start=sessions[40],
        evaluation_end=sessions[-1],
        lookback_sessions=10,
        skip_sessions=1,
        windows=WindowSpec(
            train_start=sessions[40],
            train_end=sessions[80],
            validation_start=sessions[81],
            validation_end=sessions[100],
            test_start=sessions[101],
            test_end=sessions[-1],
        ),
    )
    audit = AuditLog(settings.database_path)
    first = run_experiment(
        config,
        market_path=settings.market_data_path,
        research_path=settings.research_path,
        audit=audit,
    )
    second = run_experiment(
        config,
        market_path=settings.market_data_path,
        research_path=settings.research_path,
        audit=audit,
    )
    assert first["fingerprint"]["digest"] == second["fingerprint"]["digest"]
    replay = replay_run(
        first["run_id"],
        research_path=settings.research_path,
        market_path=settings.market_data_path,
    )
    assert replay["ok"] is True
    with TestClient(create_app(settings)) as client:
        listed = client.get("/api/research/runs")
        detail = client.get(f"/api/research/runs/{first['run_id']}")
        trades = client.get(f"/api/research/runs/{first['run_id']}/trades")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 2
    assert detail.json()["label"] == "backtest"
    assert detail.json()["is_broker_execution"] is False
    assert trades.json()["note"].startswith("Simulated")


def test_buy_hold_does_not_use_same_day_close_for_entry() -> None:
    sessions = sessions_between(date(2020, 1, 2), date(2020, 2, 28))
    bars = {_session: _bar(_session, "100", "200") for _session in sessions}
    config = _config(
        data_start=sessions[0],
        data_end=sessions[-1],
        evaluation_start=sessions[0],
        evaluation_end=sessions[-1],
    )
    result = DailyBacktestEngine().run_experiment_strategy(
        strategy_id="spy_buy_hold",
        config=config,
        bars=bars,
        lookback=0,
        skip=0,
        mode="buy_hold",
    )
    assert result.trades
    assert result.trades[0].price == Decimal("100")
