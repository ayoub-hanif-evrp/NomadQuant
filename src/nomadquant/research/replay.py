"""Deterministic replay checks for stored simulated decisions."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from nomadquant.marketdata.calendar import sessions_between
from nomadquant.research.models import ExperimentConfig
from nomadquant.research.runner import load_session_bars
from nomadquant.research.signals import momentum_return, target_from_momentum
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
    symbol = config.symbols[0]
    bars = load_session_bars(
        market_path,
        symbol=symbol,
        feed=config.feed,
        start=config.data_start,
        end=config.data_end,
    )
    closes = {session: bar.close for session, bar in bars.items()}
    sessions = sessions_between(config.data_start, config.data_end)
    decisions = [
        item
        for item in store.decisions(run_id, strategy_id=config.strategy_id)
        if item["signal"] == "tsmom_rebalance"
    ]
    checked = 0
    mismatches: list[dict[str, object]] = []
    for decision in decisions:
        session = date.fromisoformat(decision["session_date"])
        value = momentum_return(
            closes,
            sessions,
            session,
            config.lookback_sessions,
            config.skip_sessions,
        )
        expected = target_from_momentum(value)
        recorded = Decimal(decision["proposed_target_weight"])
        features = {
            "lookback_sessions": str(config.lookback_sessions),
            "skip_sessions": str(config.skip_sessions),
            "momentum_return": "null" if value is None else str(value),
            "close": str(bars[session].close) if session in bars else "missing",
            "information_cutoff": decision["feature_inputs"].get("information_cutoff", ""),
        }
        # Use recorded feature close when present so replay matches stored inputs.
        if "close" in decision["feature_inputs"]:
            features["close"] = decision["feature_inputs"]["close"]
        if "momentum_return" in decision["feature_inputs"]:
            features["momentum_return"] = decision["feature_inputs"]["momentum_return"]
        digest = hashlib.sha256(
            json.dumps(
                {
                    "session": session.isoformat(),
                    "features": decision["feature_inputs"],
                    "weight": str(recorded),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        checked += 1
        if expected != recorded:
            mismatches.append(
                {
                    "session_date": session.isoformat(),
                    "expected_weight": str(expected),
                    "recorded_weight": str(recorded),
                    "kind": "weight_mismatch",
                }
            )
        if digest != decision["evidence_hash"]:
            mismatches.append(
                {
                    "session_date": session.isoformat(),
                    "kind": "evidence_hash_mismatch",
                    "expected_hash": digest,
                    "recorded_hash": decision["evidence_hash"],
                }
            )
    return {
        "run_id": run_id,
        "checked_decisions": checked,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
        "ok": len(mismatches) == 0,
        "label": "simulated_replay",
        "is_broker_execution": False,
    }
