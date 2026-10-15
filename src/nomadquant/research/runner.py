"""Load market bars and run a registered experiment offline."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from nomadquant.audit import AuditLog
from nomadquant.marketdata.store import MarketStore
from nomadquant.research import ENGINE_VERSION
from nomadquant.research.engine import DailyBacktestEngine, IncompleteResearchData, SessionBar
from nomadquant.research.fingerprint import dataset_fingerprint
from nomadquant.research.models import ExperimentConfig, StrategyResult
from nomadquant.research.store import ResearchStore


def load_config(path: str | Path) -> ExperimentConfig:
    text = Path(path).read_text(encoding="utf-8")
    payload = json.loads(text)
    return ExperimentConfig.model_validate(payload)


def git_commit_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    sha = completed.stdout.strip()
    return sha or None


def load_session_bars(
    market_path: str | Path,
    *,
    symbol: str,
    feed: str,
    start: date,
    end: date,
) -> dict[date, SessionBar]:
    store = MarketStore(market_path)
    return {
        session: SessionBar(
            session_date=session,
            open=open_,
            high=high,
            low=low,
            close=close,
        )
        for session, open_, high, low, close in store.session_ohlc(symbol, feed, start, end)
    }


def run_experiment(
    config: ExperimentConfig,
    *,
    market_path: str | Path,
    research_path: str | Path,
    audit: AuditLog,
) -> dict[str, Any]:
    research = ResearchStore(research_path)
    now = datetime.now(UTC).isoformat()
    research.upsert_experiment(
        {
            "experiment_id": config.experiment_id,
            "hypothesis_id": config.hypothesis_id,
            "title": config.title,
            "description": config.description,
            "citations": config.citations,
            "config": json.loads(config.model_dump_json()),
            "created_at": now,
        }
    )
    fingerprint = dataset_fingerprint(
        market_path,
        symbols=config.symbols,
        feed=config.feed,
        start=config.data_start,
        end=config.data_end,
    )
    audit_run_id = audit.start_run(
        run_type="research_backtest",
        component="backtest",
        title=config.title,
        summary=f"Starting offline backtest {config.experiment_id}.",
        payload={
            "experiment_id": config.experiment_id,
            "hypothesis_id": config.hypothesis_id,
            "config": json.loads(config.model_dump_json()),
            "dataset": fingerprint,
            "engine_version": ENGINE_VERSION,
            "label": "backtest",
            "is_broker_execution": False,
        },
    )
    run_id = research.start_run(
        {
            "experiment_id": config.experiment_id,
            "created_at": now,
            "git_commit": git_commit_sha(),
            "engine_version": ENGINE_VERSION,
            "dataset_fingerprint": str(fingerprint["digest"]),
            "config": json.loads(config.model_dump_json()),
            "audit_run_id": audit_run_id,
        }
    )
    try:
        if len(config.symbols) != 1:
            raise ValueError("Phase 3 supports a single-symbol experiment.")
        symbol = config.symbols[0]
        bars = load_session_bars(
            market_path,
            symbol=symbol,
            feed=config.feed,
            start=config.data_start,
            end=config.data_end,
        )
        engine = DailyBacktestEngine()
        primary = engine.run_experiment_strategy(
            strategy_id=config.strategy_id,
            config=config,
            bars=bars,
            lookback=config.lookback_sessions,
            skip=config.skip_sessions,
            mode="momentum",
        )
        results = {
            config.strategy_id: primary,
            "spy_buy_hold": engine.run_experiment_strategy(
                strategy_id="spy_buy_hold",
                config=config,
                bars=bars,
                lookback=0,
                skip=0,
                mode="buy_hold",
            ),
            "cash": engine.run_experiment_strategy(
                strategy_id="cash",
                config=config,
                bars=bars,
                lookback=0,
                skip=0,
                mode="cash",
            ),
            "tsmom_6m": engine.run_experiment_strategy(
                strategy_id="tsmom_6m",
                config=config,
                bars=bars,
                lookback=126,
                skip=0,
                mode="momentum",
            ),
        }
        for strategy_id, result in results.items():
            payload = _result_dict(result)
            research.save_strategy_result(run_id, strategy_id, payload)
            for decision in result.decisions[:50]:
                audit.record_decision(
                    source_type="backtest",
                    symbols=[decision.symbol],
                    decision_action=decision.action,
                    decision_status="simulated",
                    rationale_summary=decision.rationale[:500],
                    evidence_summary=f"evidence_hash={decision.evidence_hash}",
                    warnings="; ".join(decision.warnings),
                    market_data_snapshot=decision.data_cutoff,
                    proposed_notional=str(decision.proposed_target_weight),
                    backtest_id=str(run_id),
                    explanation={
                        "run_id": run_id,
                        "strategy_id": strategy_id,
                        "session_date": decision.session_date.isoformat(),
                        "feature_inputs": decision.feature_inputs,
                        "is_simulated": True,
                        "is_broker_order": False,
                    },
                )
        primary_test = next((item for item in primary.metrics if item.window == "test"), None)
        net = (
            "n/a"
            if primary_test is None or primary_test.net_return is None
            else str(primary_test.net_return)
        )
        summary = f"Offline price-only backtest finished. Primary test net return={net}."
        caveats = list(config.caveats) + [
            "Result label: backtest. Not paper trading. Not a broker fill.",
            "Research mode: price-only. Dividends and total return are excluded.",
            "No statistical significance claim is made.",
            "Multiple-testing warning: only this pre-registered configuration was evaluated.",
        ]
        research.finish_run(
            run_id,
            {
                "finished_at": datetime.now(UTC).isoformat(),
                "status": "succeeded",
                "outcome_summary": summary,
                "caveats": caveats,
            },
        )
        audit.finish_run(
            audit_run_id,
            status="succeeded",
            summary=summary,
            payload={
                "research_run_id": run_id,
                "dataset_fingerprint": fingerprint["digest"],
                "strategies": list(results.keys()),
            },
        )
        return {"run_id": run_id, "audit_run_id": audit_run_id, "fingerprint": fingerprint}
    except (IncompleteResearchData, ValueError, RuntimeError) as exc:
        message = str(exc)
        research.finish_run(
            run_id,
            {
                "finished_at": datetime.now(UTC).isoformat(),
                "status": "failed",
                "outcome_summary": "Experiment failed closed.",
                "caveats": list(config.caveats),
                "error_code": type(exc).__name__,
                "error_message_safe": message[:500],
            },
        )
        audit.finish_run(
            audit_run_id,
            status="failed",
            summary="Experiment failed closed.",
            error_code=type(exc).__name__,
            error_message_safe=message[:500],
            payload={"research_run_id": run_id},
        )
        raise


def _result_dict(result: StrategyResult) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(result.model_dump_json())
    return payload
