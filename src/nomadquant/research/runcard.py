"""Immutable research run cards. Descriptive metrics are not significance claims."""

from __future__ import annotations

from typing import Any

from nomadquant.research.models import ExperimentConfig

LABEL = "BACKTEST — NOT REAL OR PAPER BROKER TRADING"


def build_run_card(
    *,
    run_id: int,
    config: ExperimentConfig,
    git_commit: str | None,
    fingerprint: dict[str, object],
    metrics: list[dict[str, Any]],
    decision_count: int,
    trade_count: int,
    replay_verdict: str,
    caveats: list[str],
    status: str,
) -> dict[str, Any]:
    return {
        "label": LABEL,
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "hypothesis_id": config.hypothesis_id,
        "title": config.title,
        "citations": config.citations,
        "strategy_id": config.strategy_id,
        "engine_version": config.engine_version,
        "git_commit": git_commit,
        "provider": "alpaca",
        "feed": config.feed,
        "adjustment": config.adjustment,
        "research_mode": config.research_mode,
        "data_start": config.data_start.isoformat(),
        "data_end": config.data_end.isoformat(),
        "evaluation_start": config.evaluation_start.isoformat(),
        "evaluation_end": config.evaluation_end.isoformat(),
        "dataset_fingerprint": fingerprint["digest"],
        "bar_count": fingerprint.get("bar_count"),
        "revision_count": fingerprint.get("revision_count"),
        "initial_capital_usd": str(config.initial_capital_usd),
        "costs": config.costs.model_dump(mode="json"),
        "signal_timing": "close_known_after_1630_America_New_York",
        "execution_timing": "next_session_open",
        "benchmarks": config.benchmarks,
        "windows": config.windows.model_dump(mode="json"),
        "metrics": metrics,
        "simulated_trade_count": trade_count,
        "simulated_decision_count": decision_count,
        "warnings": caveats,
        "reproducibility": replay_verdict,
        "status": status,
        "inference": {
            "statistical_significance": "NOT_EVALUABLE",
            "reason": (
                "One pre-registered price-only path. Sharpe and Sortino are descriptive. "
                "No p-value, deflated Sharpe, or trade-permutation alpha test is reported."
            ),
        },
        "is_broker_execution": False,
        "is_paper_trading": False,
    }
