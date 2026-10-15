"""Deterministic checks for a stored research run.

A PASS means the artifact is internally consistent. It is not a claim of
statistical credibility or profitability.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.research.models import ExperimentConfig
from nomadquant.research.replay import replay_run
from nomadquant.research.store import ResearchStore

VERDICTS = ("PASS", "FAIL", "NOT_EVALUABLE", "INVALID_ARTIFACT")


def verify_run(
    run_id: int,
    *,
    research_path: str | Path,
    market_path: str | Path,
) -> dict[str, Any]:
    store = ResearchStore(research_path)
    run = store.get_run(run_id)
    if run is None:
        return _report(run_id, [_check("run_exists", "INVALID_ARTIFACT", "Run was not found.")])
    checks: list[dict[str, str]] = [_check("run_exists", "PASS", "Run row exists.")]
    try:
        config = ExperimentConfig.model_validate(run["config"])
        checks.append(_check("configuration", "PASS", "Configuration parsed."))
    except ValueError as exc:
        checks.append(_check("configuration", "INVALID_ARTIFACT", str(exc)))
        return _report(run_id, checks)

    if run["dataset_fingerprint"]:
        checks.append(_check("dataset_fingerprint_recorded", "PASS", run["dataset_fingerprint"]))
    else:
        checks.append(
            _check("dataset_fingerprint_recorded", "INVALID_ARTIFACT", "Fingerprint missing.")
        )

    replay = replay_run(run_id, research_path=research_path, market_path=market_path)
    replay_verdict = str(replay["verdict"])
    if replay_verdict == "NOT_REPRODUCIBLE":
        checks.append(
            _check("independent_replay", "FAIL", "NOT_REPRODUCIBLE: " + str(replay["summary"]))
        )
    elif replay_verdict in VERDICTS:
        checks.append(_check("independent_replay", replay_verdict, str(replay["summary"])))
    else:
        checks.append(_check("independent_replay", "INVALID_ARTIFACT", replay_verdict))

    decisions = store.decisions(run_id, strategy_id=config.strategy_id)
    if not decisions:
        checks.append(
            _check("decision_history", "NOT_EVALUABLE", "No simulated decisions were stored.")
        )
    else:
        future = [
            item
            for item in decisions
            if item["signal"] == "tsmom_rebalance"
            and item["fill_session"]
            and item["fill_session"] <= item["session_date"]
        ]
        checks.append(
            _check(
                "no_same_day_close_fill",
                "FAIL" if future else "PASS",
                f"{len(future)} same-day momentum fills.",
            )
        )
        ordered = all(
            _ordered(item["data_cutoff"], item["decision_timestamp"]) for item in decisions
        )
        checks.append(
            _check(
                "timestamps_ordered",
                "PASS" if ordered else "FAIL",
                "Decision timestamp is at or after the data cutoff.",
            )
        )

    negative_cash = any(Decimal(item["portfolio_after"].get("cash", "0")) < 0 for item in decisions)
    checks.append(
        _check(
            "cash_non_negative",
            "FAIL" if negative_cash else "PASS",
            "Portfolio snapshots stay non-negative.",
        )
    )
    shorts = False
    for item in decisions:
        positions = item["portfolio_after"].get("positions", "")
        for part in positions.split(","):
            if ":" in part and Decimal(part.split(":", 1)[1]) < 0:
                shorts = True
    checks.append(
        _check("no_short", "FAIL" if shorts else "PASS", "No short quantity in snapshots.")
    )

    metrics = store.metrics(run_id)
    strategy_ids = {item["strategy_id"] for item in metrics}
    missing = [name for name in ("spy_buy_hold", "cash") if name not in strategy_ids]
    checks.append(
        _check(
            "benchmarks_present",
            "FAIL" if missing else "PASS",
            "Missing " + ",".join(missing) if missing else "Benchmarks stored.",
        )
    )
    trades = store.trades(run_id, strategy_id=config.strategy_id)
    checks.append(
        _check("trade_history_stored", "PASS", f"{len(trades)} simulated primary trades.")
    )
    leaked = any(token in str(run).lower() for token in ("alpaca_api_secret", "bearer "))
    checks.append(
        _check(
            "no_credentials", "FAIL" if leaked else "PASS", "No credential fields in the run row."
        )
    )
    labeled = run["label"] == "backtest" and run["is_broker_execution"] is False
    checks.append(
        _check(
            "backtest_label",
            "PASS" if labeled else "FAIL",
            "Run is labeled as an offline backtest.",
        )
    )
    checks.append(
        _check(
            "statistical_significance",
            "NOT_EVALUABLE",
            "A reproducible backtest is not a significance result.",
        )
    )
    return _report(run_id, checks)


def _ordered(cutoff: str, decision_time: str) -> bool:
    try:
        return datetime.fromisoformat(cutoff) <= datetime.fromisoformat(decision_time)
    except ValueError:
        return False


def _check(name: str, verdict: str, detail: str) -> dict[str, str]:
    if verdict not in VERDICTS:
        raise ValueError(verdict)
    return {"name": name, "verdict": verdict, "detail": detail}


def _report(run_id: int, checks: list[dict[str, str]]) -> dict[str, Any]:
    structural = [item for item in checks if item["name"] != "statistical_significance"]
    if any(item["verdict"] == "INVALID_ARTIFACT" for item in checks):
        overall = "INVALID_ARTIFACT"
    elif any(item["verdict"] == "FAIL" for item in structural):
        overall = "FAIL"
    elif any(item["verdict"] == "NOT_EVALUABLE" for item in structural):
        overall = "NOT_EVALUABLE"
    else:
        overall = "PASS"
    return {
        "run_id": run_id,
        "verdict": overall,
        "checks": checks,
        "label": "backtest_verification",
        "is_statistical_claim": False,
        "is_broker_execution": False,
    }
