"""Run 2's missing-momentum row is a frozen legacy convention, not a rewritten PASS."""

from datetime import date
from decimal import Decimal

from nomadquant.marketdata.calendar import sessions_between
from nomadquant.research.engine import DailyBacktestEngine, SessionBar
from nomadquant.research.models import CostModel, ExperimentConfig, WindowSpec
from nomadquant.research.replay import _replay_convention

_SESSIONS = sessions_between(date(2019, 1, 2), date(2019, 2, 4))


def _config(convention: str) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="legacy-check",
        hypothesis_id="H",
        title="Legacy convention",
        description="Fixture",
        symbols=["SPY"],
        feed="sip",
        data_start=_SESSIONS[0],
        data_end=_SESSIONS[-1],
        evaluation_start=date(2019, 2, 1),
        evaluation_end=_SESSIONS[-1],
        windows=WindowSpec(
            train_start=date(2019, 2, 1),
            train_end=_SESSIONS[-1],
            validation_start=date(2019, 2, 1),
            validation_end=_SESSIONS[-1],
            test_start=date(2019, 2, 1),
            test_end=_SESSIONS[-1],
        ),
        strategy_id="spy_tsmom_12_1",
        lookback_sessions=252,
        skip_sessions=21,
        costs=CostModel(),
        benchmarks=[],
        signal_convention=convention,  # type: ignore[arg-type]
    )


def _bars() -> dict[date, SessionBar]:
    return {
        session: SessionBar(
            session, Decimal("270"), Decimal("271"), Decimal("269"), Decimal("270.08")
        )
        for session in _SESSIONS
    }


def test_current_convention_does_not_treat_missing_momentum_as_cash() -> None:
    bars = _bars()
    current = DailyBacktestEngine().run_experiment_strategy(
        strategy_id="spy_tsmom_12_1",
        config=_config("insufficient_data_v1"),
        bars=bars,
        lookback=252,
        skip=21,
        mode="momentum",
    )
    assert current.decisions[0].signal == "insufficient_data"
    assert current.trades == []
    legacy = DailyBacktestEngine().run_experiment_strategy(
        strategy_id="spy_tsmom_12_1",
        config=_config("legacy_null_is_cash_v1"),
        bars=bars,
        lookback=252,
        skip=21,
        mode="momentum",
    )
    assert legacy.decisions[0].signal == "tsmom_rebalance"
    assert legacy.decisions[0].feature_inputs["momentum_return"] == "null"
    assert legacy.decisions[0].proposed_target_weight == Decimal("0")


def test_stored_null_momentum_selects_the_legacy_convention() -> None:
    convention, source = _replay_convention(
        [
            {
                "signal": "tsmom_rebalance",
                "feature_inputs": {"momentum_return": "null"},
            }
        ],
        _config("insufficient_data_v1"),
    )
    assert convention == "legacy_null_is_cash_v1"
    assert source == "stored_null_momentum"
