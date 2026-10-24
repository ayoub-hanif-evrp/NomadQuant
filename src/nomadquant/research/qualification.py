"""Label a daily-strategy study. The label is not permission to trade."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from nomadquant.daily.registry import SPECS
from nomadquant.daily.walkforward import walk_forward
from nomadquant.marketdata.evidence import dataset_evidence

_MIN_SESSIONS = 220


def qualify_daily_strategies(
    prices: dict[str, dict[date, Decimal]],
    sessions: list[date],
) -> dict[str, Any]:
    """Walk-forward the registered rules and refuse a qualification the data cannot support."""
    evidence = dataset_evidence()
    usable = [day for day in sessions if day in (prices.get("SPY") or {})]
    study = walk_forward(prices, sessions)
    buy_hold = _buy_hold(prices.get("SPY") or {}, usable)
    state = _state(len(usable), evidence, study)
    return {
        "label": "historical_research",
        "state": state,
        "permission_to_trade": False,
        "reason": _reason(state, evidence),
        "dataset": evidence,
        "strategies": [spec.strategy_id for spec in SPECS.values()],
        "parameter_refit": False,
        "walk_forward": study,
        "benchmarks": {
            "cash_return": "0",
            "spy_buy_hold": buy_hold,
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


def _state(sample: int, evidence: dict[str, Any], study: dict[str, object]) -> str:
    if sample < _MIN_SESSIONS or study.get("status") == "insufficient_history":
        return "INSUFFICIENT_DATA"
    if evidence.get("point_in_time_total_return") is not True:
        return "NOT_EVALUABLE"
    folds = study.get("folds")
    if not isinstance(folds, list) or len(folds) < 2:
        return "INCONCLUSIVE"
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
