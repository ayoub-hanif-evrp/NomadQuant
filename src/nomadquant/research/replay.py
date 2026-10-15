"""Independent replay. Recorded fields are the subject, not the evidence."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from nomadquant.research.engine import DailyBacktestEngine
from nomadquant.research.fingerprint import dataset_fingerprint
from nomadquant.research.models import ExperimentConfig
from nomadquant.research.store import ResearchStore


def replay_run(
    run_id: int,
    *,
    research_path: str | Path,
    market_path: str | Path,
) -> dict[str, object]:
    store = ResearchStore(research_path)
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"Unknown research run {run_id}.")
    config = ExperimentConfig.model_validate(run["config"])
    try:
        fingerprint = dataset_fingerprint(
            market_path,
            symbols=config.symbols,
            feed=config.feed,
            start=config.data_start,
            end=config.data_end,
        )
    except OSError:
        return _verdict(run_id, "NOT_REPRODUCIBLE", [], "Market database could not be read.")
    if fingerprint["digest"] != run["dataset_fingerprint"]:
        return _verdict(
            run_id,
            "NOT_REPRODUCIBLE",
            [
                {
                    "kind": "dataset_fingerprint_mismatch",
                    "recorded": run["dataset_fingerprint"],
                    "current": fingerprint["digest"],
                }
            ],
            "The stored bars no longer match the fingerprint recorded for this run.",
        )
    from nomadquant.research.runner import load_session_bars

    bars = load_session_bars(
        market_path,
        symbol=config.symbols[0],
        feed=config.feed,
        start=config.data_start,
        end=config.data_end,
    )
    if not bars:
        return _verdict(
            run_id, "NOT_REPRODUCIBLE", [], "No source bars were available to recompute."
        )

    recomputed = DailyBacktestEngine().run_experiment_strategy(
        strategy_id=config.strategy_id,
        config=config,
        bars=bars,
        lookback=config.lookback_sessions,
        skip=config.skip_sessions,
        mode="momentum",
    )
    mismatches: list[dict[str, object]] = []
    recorded_decisions = store.decisions(run_id, strategy_id=config.strategy_id)
    recomputed_by_key = {
        (item.session_date.isoformat(), item.signal): item for item in recomputed.decisions
    }
    recorded_keys = {(item["session_date"], item["signal"]) for item in recorded_decisions}
    for key in recomputed_by_key:
        if key not in recorded_keys:
            mismatches.append(
                {
                    "kind": "extra_recomputed_decision",
                    "session_date": key[0],
                    "signal": key[1],
                }
            )
    if len(recorded_decisions) != len(recomputed.decisions):
        mismatches.append(
            {
                "kind": "decision_count_mismatch",
                "recorded": len(recorded_decisions),
                "recomputed": len(recomputed.decisions),
            }
        )

    for recorded in recorded_decisions:
        key = (recorded["session_date"], recorded["signal"])
        fresh = recomputed_by_key.get(key)
        if fresh is None:
            mismatches.append({"kind": "missing_recomputed_decision", "session_date": key[0]})
            continue
        if Decimal(recorded["proposed_target_weight"]) != fresh.proposed_target_weight:
            mismatches.append(
                {
                    "kind": "weight_mismatch",
                    "session_date": key[0],
                    "recorded": recorded["proposed_target_weight"],
                    "recomputed": str(fresh.proposed_target_weight),
                }
            )
        if recorded["feature_inputs"].get("momentum_return") != fresh.feature_inputs.get(
            "momentum_return"
        ):
            mismatches.append({"kind": "feature_mismatch", "session_date": key[0]})
        if recorded["feature_inputs"].get("close") != fresh.feature_inputs.get("close"):
            mismatches.append({"kind": "close_mismatch", "session_date": key[0]})
        recorded_fill = recorded["fill_session"]
        fresh_fill = None if fresh.fill_session is None else fresh.fill_session.isoformat()
        if recorded_fill != fresh_fill:
            mismatches.append({"kind": "execution_timing_mismatch", "session_date": key[0]})
        if recorded["evidence_hash"] != fresh.evidence_hash:
            mismatches.append({"kind": "evidence_hash_mismatch", "session_date": key[0]})
        before = recorded.get("portfolio_before") or {}
        after_rec = recorded.get("portfolio_after") or {}
        if isinstance(before, dict) and isinstance(fresh.portfolio_before, dict):
            if _decimal_field(before, "cash") != _decimal_field(fresh.portfolio_before, "cash"):
                mismatches.append(
                    {"kind": "portfolio_before_cash_mismatch", "session_date": key[0]}
                )
            if _decimal_field(before, "equity") != _decimal_field(fresh.portfolio_before, "equity"):
                mismatches.append(
                    {"kind": "portfolio_before_equity_mismatch", "session_date": key[0]}
                )
        if isinstance(after_rec, dict) and isinstance(fresh.portfolio_after, dict):
            if _decimal_field(after_rec, "cash") != _decimal_field(fresh.portfolio_after, "cash"):
                mismatches.append({"kind": "portfolio_after_cash_mismatch", "session_date": key[0]})
            after_eq = _decimal_field(after_rec, "equity")
            fresh_eq = _decimal_field(fresh.portfolio_after, "equity")
            if after_eq != fresh_eq:
                mismatches.append(
                    {"kind": "portfolio_after_equity_mismatch", "session_date": key[0]}
                )

    recorded_trades = store.trades(run_id, strategy_id=config.strategy_id)
    if len(recorded_trades) != len(recomputed.trades):
        mismatches.append(
            {
                "kind": "trade_count_mismatch",
                "recorded": len(recorded_trades),
                "recomputed": len(recomputed.trades),
            }
        )
    for recorded_trade, fresh_trade in zip(recorded_trades, recomputed.trades, strict=False):
        if (
            recorded_trade["session_date"] != fresh_trade.session_date.isoformat()
            or Decimal(recorded_trade["price"]) != fresh_trade.price
            or Decimal(recorded_trade["quantity"]) != fresh_trade.quantity
            or Decimal(recorded_trade["commission"]) != fresh_trade.commission
            or Decimal(recorded_trade["spread_cost"]) != fresh_trade.spread_cost
            or Decimal(recorded_trade["slippage_cost"]) != fresh_trade.slippage_cost
        ):
            mismatches.append(
                {"kind": "trade_mismatch", "session_date": recorded_trade["session_date"]}
            )

    recorded_equity = store.equity(run_id, strategy_id=config.strategy_id)
    recomputed_equity = recomputed.equity
    if len(recorded_equity) != len(recomputed_equity):
        mismatches.append(
            {
                "kind": "equity_point_count_mismatch",
                "recorded": len(recorded_equity),
                "recomputed": len(recomputed_equity),
            }
        )
    for recorded_point, fresh_point in zip(recorded_equity, recomputed_equity, strict=False):
        if recorded_point["session_date"] != fresh_point.session_date.isoformat():
            mismatches.append(
                {
                    "kind": "equity_session_mismatch",
                    "recorded": recorded_point["session_date"],
                    "recomputed": fresh_point.session_date.isoformat(),
                }
            )
            break
        if Decimal(recorded_point["equity"]) != fresh_point.equity:
            mismatches.append(
                {
                    "kind": "equity_point_mismatch",
                    "session_date": recorded_point["session_date"],
                }
            )
            break
        if Decimal(recorded_point["cash"]) != fresh_point.cash:
            mismatches.append(
                {
                    "kind": "equity_cash_mismatch",
                    "session_date": recorded_point["session_date"],
                }
            )
            break

    recorded_metrics = [
        item
        for item in store.metrics(run_id)
        if item["strategy_id"] == config.strategy_id and item["window"] == "test"
    ]
    fresh_test = next((item for item in recomputed.metrics if item.window == "test"), None)
    if recorded_metrics and fresh_test is not None:
        recorded_net = recorded_metrics[0].get("net_return")
        if recorded_net is not None and fresh_test.net_return is not None:
            if Decimal(str(recorded_net)) != fresh_test.net_return:
                mismatches.append(
                    {
                        "kind": "metric_net_return_mismatch",
                        "recorded": str(recorded_net),
                        "recomputed": str(fresh_test.net_return),
                    }
                )

    if fingerprint.get("digest") and not bars:
        mismatches.append({"kind": "missing_source_observations"})

    verdict = "PASS" if not mismatches else "FAIL"
    payload = _verdict(
        run_id,
        verdict,
        mismatches,
        "Independent recomputation finished. PASS covers decisions, trades, "
        "equity points, portfolio cash/equity snapshots, and locked-test net return when present.",
    )
    payload["checked_decisions"] = len(recorded_decisions)
    payload["checks_scope"] = [
        "dataset_fingerprint",
        "decision_count_and_keys",
        "decision_weights_features_fills_hashes",
        "portfolio_cash_equity_snapshots",
        "trades",
        "equity_points",
        "test_net_return_when_present",
    ]
    return payload


def _decimal_field(payload: Mapping[str, object], key: str) -> Decimal | None:
    raw = payload.get(key)
    if raw is None:
        return None
    return Decimal(str(raw))


def _verdict(
    run_id: int,
    verdict: str,
    mismatches: list[dict[str, object]],
    summary: str,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "checked_decisions": 0,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:40],
        "ok": verdict == "PASS",
        "verdict": verdict,
        "summary": summary,
        "label": "simulated_replay",
        "is_broker_execution": False,
        "independent": True,
    }
