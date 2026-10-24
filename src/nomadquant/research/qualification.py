"""Locked qualification of the daily book. The label is not permission to trade."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.daily.registry import SPECS
from nomadquant.daily.walkforward import walk_forward
from nomadquant.marketdata.actions import series_fingerprint
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.evidence import dataset_evidence
from nomadquant.research.metrics import compute_metrics
from nomadquant.research.oos import CAPITAL, WARMUP, simulate

_MIN_SESSIONS = 220
_MIN_TRADES = 2
_MAX_DRAWDOWN = Decimal("0.25")
_SPREAD_BPS = Decimal("1")
_SLIPPAGE_BPS = Decimal("1")
PRIMARY_STRATEGY_ID = "etf_trend_sma_v1"
GATES = {
    "min_sessions": _MIN_SESSIONS,
    "min_oos_trades": _MIN_TRADES,
    "max_drawdown": format(_MAX_DRAWDOWN, "f"),
    "spread_bps": format(_SPREAD_BPS, "f"),
    "slippage_bps": format(_SLIPPAGE_BPS, "f"),
    "stress": "twice_spread_and_slippage",
    "execution": "signal_close_fill_next_close",
    "paper_execution": "market_order_during_the_session",
    "comparable_to_paper_fills": False,
    "session_market_model": "NOT_EVALUABLE",
    "session_market_reason": "daily_closes_do_not_price_an_intraday_market_order",
    "primary_strategy_id": PRIMARY_STRATEGY_ID,
    "parameter_refit": False,
}


def qualify_daily_strategies(
    prices: dict[str, dict[date, Decimal]],
    sessions: list[date],
    *,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Judge the locked daily book. Raw prices stay NOT_EVALUABLE."""
    chosen = dataset_evidence() if evidence is None else evidence
    usable = [day for day in sessions if day in (prices.get("SPY") or {})]
    if chosen.get("point_in_time_total_return") is not True:
        return _unqualified(prices, sessions, usable, chosen, _state(len(usable), chosen))
    mismatch = _fingerprint_mismatch(prices, chosen)
    if mismatch is not None:
        blocked = {**chosen, "point_in_time_total_return": False, "reason": mismatch}
        return _unqualified(prices, sessions, usable, blocked, "NOT_EVALUABLE")
    return _evaluate(prices, sessions, usable, chosen)


def append_qualification_trial(path: str | Path, report: dict[str, Any]) -> None:
    """Append one trial, including a failed or unevaluable one. Rows are not replaced."""
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS qualification_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                state TEXT NOT NULL,
                reason TEXT NOT NULL,
                report_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO qualification_trials (recorded_at, state, reason, report_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                str(report.get("state")),
                str(report.get("reason")),
                json.dumps(report, sort_keys=True),
            ),
        )


def _evaluate(
    prices: dict[str, dict[date, Decimal]],
    sessions: list[date],
    usable: list[date],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    ordered = sorted(set(usable))
    if len(ordered) < _MIN_SESSIONS:
        return _result(
            evidence, "INSUFFICIENT_DATA", "fewer_than_220_sessions", ordered, None, None
        )
    expected = sessions_between(ordered[0], ordered[-1])
    if ordered != expected:
        return _result(evidence, "INCONCLUSIVE", "missing_observations", ordered, None, None)
    base = simulate(prices, ordered, spread_bps=_SPREAD_BPS, slippage_bps=_SLIPPAGE_BPS)
    stress = simulate(
        prices,
        ordered,
        spread_bps=_SPREAD_BPS * 2,
        slippage_bps=_SLIPPAGE_BPS * 2,
    )
    if base.status != "completed" or not base.out_of_sample:
        return _result(
            evidence, "INSUFFICIENT_DATA", "fewer_than_220_sessions", ordered, base, stress
        )
    metrics = compute_metrics(
        window="out_of_sample",
        equity=base.out_of_sample,
        trades=[trade for trade in base.trades if trade.session_date >= ordered[WARMUP]],
        start_capital=CAPITAL,
        opening_equity=base.opening,
    )
    stressed = compute_metrics(
        window="out_of_sample_twice_costs",
        equity=stress.out_of_sample,
        trades=stress.trades,
        start_capital=CAPITAL,
        opening_equity=stress.opening,
    )
    state, reason = _judge(
        metrics.net_return,
        metrics.sharpe,
        metrics.max_drawdown,
        metrics.trade_count,
        stressed.net_return,
        base.fold_returns,
        base.matched_return,
    )
    return _result(evidence, state, reason, ordered, base, stress, metrics, stressed)


def _judge(
    net: Decimal | None,
    sharpe: Decimal | None,
    drawdown: Decimal | None,
    trades: int,
    stress_net: Decimal | None,
    folds: list[Decimal],
    matched: Decimal | None,
) -> tuple[str, str]:
    if net is None:
        return "INCONCLUSIVE", "net_return_undefined"
    if net <= 0:
        return "FAILED", "oos_net_return_not_positive"
    if drawdown is None or drawdown > _MAX_DRAWDOWN:
        return "FAILED", "drawdown_above_0_25"
    if sharpe is None:
        return "INCONCLUSIVE", "sharpe_undefined"
    if sharpe <= 0:
        return "FAILED", "sharpe_not_positive"
    if stress_net is None or stress_net <= 0:
        return "FAILED", "edge_absent_at_twice_costs"
    if trades < _MIN_TRADES:
        return "INCONCLUSIVE", "fewer_than_2_oos_trades"
    if len(folds) < 2 or any(item <= 0 for item in folds):
        return "INCONCLUSIVE", "fold_signs_disagree"
    if matched is None or net <= matched:
        return "INCONCLUSIVE", "did_not_beat_matched_spy"
    return "RESEARCH_QUALIFIED", "primary_cleared_locked_gates"


def _result(
    evidence: dict[str, Any],
    state: str,
    reason: str,
    usable: list[date],
    base: Any,
    stress: Any,
    metrics: Any = None,
    stressed: Any = None,
) -> dict[str, Any]:
    folds = [] if base is None else [format(item, "f") for item in base.fold_returns]
    return {
        "label": "historical_research",
        "state": state,
        "permission_to_trade": False,
        "reason": reason,
        "dataset": {key: value for key, value in evidence.items() if key != "derived_prices"},
        "strategies": [spec.strategy_id for spec in SPECS.values()],
        "primary_strategy_id": PRIMARY_STRATEGY_ID,
        "parameter_refit": False,
        "gates": GATES,
        **_execution_note(),
        "walk_forward": {"label": "historical_research", "status": "completed", "folds": folds},
        "benchmarks": {
            "cash_return": "0",
            "spy_buy_hold": None
            if base is None or base.full_return is None
            else format(base.full_return, "f"),
            "spy_buy_hold_matched": None
            if base is None or base.matched_return is None
            else format(base.matched_return, "f"),
            "label": "hypothetical_not_broker",
        },
        "costs": {
            "spread_bps": format(_SPREAD_BPS, "f"),
            "slippage_bps": format(_SLIPPAGE_BPS, "f"),
            "commission_usd": "0",
            "stress": "twice_spread_and_slippage",
            "stress_net_return": None
            if stressed is None or stressed.net_return is None
            else format(stressed.net_return, "f"),
        },
        "metrics": _metric_view(metrics),
        "trials_recorded": 1,
        "multiple_testing_adjustment": "primary_book_predeclared_no_parameter_search",
        "sample_sessions": len(usable),
        "regimes": _regimes(base),
    }


def _regimes(base: Any) -> dict[str, str]:
    if base is None:
        return {}
    return {key: format(value, "f") for key, value in base.regimes.items()}


def _metric_view(metrics: Any) -> dict[str, str | int | None]:
    if metrics is None:
        return {}
    return {
        "net_return": _plain(metrics.net_return),
        "sharpe": _plain(metrics.sharpe),
        "max_drawdown": _plain(metrics.max_drawdown),
        "annualized_volatility": _plain(metrics.annualized_volatility),
        "exposure": _plain(metrics.exposure),
        "turnover": _plain(metrics.turnover),
        "trade_count": metrics.trade_count,
        "sample_sessions": metrics.sample_sessions,
        "metric_method": metrics.metric_method,
    }


def _unqualified(
    prices: dict[str, dict[date, Decimal]],
    sessions: list[date],
    usable: list[date],
    evidence: dict[str, Any],
    state: str,
) -> dict[str, Any]:
    study = walk_forward(prices, sessions)
    return {
        "label": "historical_research",
        "state": state,
        "permission_to_trade": False,
        "reason": _reason(state, evidence),
        "dataset": {key: value for key, value in evidence.items() if key != "derived_prices"},
        "strategies": [spec.strategy_id for spec in SPECS.values()],
        "primary_strategy_id": PRIMARY_STRATEGY_ID,
        "parameter_refit": False,
        "gates": GATES,
        **_execution_note(),
        "walk_forward": study,
        "benchmarks": {
            "cash_return": "0",
            "spy_buy_hold": _buy_hold(prices.get("SPY") or {}, usable),
            "label": "hypothetical_not_broker",
        },
        "costs": {
            "turnover_fraction": "0.0001",
            "spread": "not_modeled",
            "commission": "not_modeled",
        },
        "trials_recorded": 1,
        "multiple_testing_adjustment": "not_applied",
        "sample_sessions": len(usable),
    }


def _execution_note() -> dict[str, object]:
    """Next-close research fills are not the paper market-order path."""
    return {
        "execution": "signal_close_fill_next_close",
        "paper_execution": "market_order_during_the_session",
        "comparable_to_paper_fills": False,
        "session_market_model": "NOT_EVALUABLE",
        "session_market_reason": "daily_closes_do_not_price_an_intraday_market_order",
    }


def _fingerprint_mismatch(
    prices: dict[str, dict[date, Decimal]], evidence: dict[str, Any]
) -> str | None:
    feed = evidence.get("feed")
    policy = evidence.get("adjustment")
    timing = evidence.get("timing")
    as_of = evidence.get("as_of")
    stored = evidence.get("series_fingerprint")
    if not isinstance(feed, str) or not isinstance(policy, str) or not isinstance(timing, str):
        return "dataset_fingerprint_missing"
    if not isinstance(as_of, str) or not isinstance(stored, str):
        return "dataset_fingerprint_missing"
    try:
        day = date.fromisoformat(as_of)
    except ValueError:
        return "dataset_fingerprint_missing"
    actual = series_fingerprint(prices, feed=feed, policy=policy, timing=timing, as_of=day)
    if actual != stored:
        return "dataset_fingerprint_mismatch"
    return None


def _state(sample: int, evidence: dict[str, Any]) -> str:
    if sample < _MIN_SESSIONS:
        return "INSUFFICIENT_DATA"
    if evidence.get("point_in_time_total_return") is not True:
        return "NOT_EVALUABLE"
    return "INCONCLUSIVE"


def _reason(state: str, evidence: dict[str, Any]) -> str:
    if state == "INSUFFICIENT_DATA":
        return "fewer_than_220_sessions"
    if state == "NOT_EVALUABLE":
        return str(evidence.get("reason") or "point_in_time_evidence_absent")
    return "no_locked_total_return_test"


def _buy_hold(series: dict[date, Decimal], usable: list[date]) -> str | None:
    if len(usable) < 2:
        return None
    start = series.get(usable[0])
    end = series.get(usable[-1])
    if start is None or end is None or start <= 0:
        return None
    return format(end / start - Decimal("1"), "f")


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")
