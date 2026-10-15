"""Adversarial checks: incomplete or altered artifacts must not PASS replay."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.audit import AuditLog
from nomadquant.marketdata.store import MarketStore, StoredBar, content_hash
from nomadquant.research.models import ExperimentConfig
from nomadquant.research.replay import replay_run
from nomadquant.research.runner import run_experiment


def _bar(session: date, close: str) -> StoredBar:
    raw = StoredBar(
        symbol="SPY",
        session_date=session,
        timestamp=datetime(session.year, session.month, session.day, 5, 0, tzinfo=UTC),
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
        available_at=datetime(session.year, session.month, session.day, 21, 30, tzinfo=UTC),
        first_retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
        content_hash="pending",
    )
    return StoredBar(**{**raw.__dict__, "content_hash": content_hash(raw)})


def _seed(tmp_path: Path) -> tuple[Path, Path, int]:
    from nomadquant.marketdata.calendar import sessions_between

    market = tmp_path / "market.sqlite"
    research = tmp_path / "research.sqlite"
    sessions = sessions_between(date(2020, 1, 2), date(2020, 6, 30))
    store = MarketStore(market)
    closes = [str(100 + (index % 20)) for index, _ in enumerate(sessions)]
    bars = [_bar(session, close) for session, close in zip(sessions, closes, strict=True)]
    store.write_bars(bars)
    config = ExperimentConfig.model_validate(
        {
            "experiment_id": "adv-tsmom",
            "hypothesis_id": "H-ADV",
            "title": "Adversarial replay fixture",
            "description": "Short window for replay tests.",
            "citations": [],
            "symbols": ["SPY"],
            "feed": "sip",
            "adjustment": "raw",
            "research_mode": "price_only",
            "data_start": sessions[0].isoformat(),
            "data_end": sessions[-1].isoformat(),
            "evaluation_start": sessions[30].isoformat(),
            "evaluation_end": sessions[-1].isoformat(),
            "windows": {
                "train_start": sessions[30].isoformat(),
                "train_end": sessions[60].isoformat(),
                "validation_start": sessions[61].isoformat(),
                "validation_end": sessions[80].isoformat(),
                "test_start": sessions[81].isoformat(),
                "test_end": sessions[-1].isoformat(),
            },
            "strategy_id": "spy_tsmom_12_1",
            "lookback_sessions": 5,
            "skip_sessions": 0,
            "initial_capital_usd": "100",
            "benchmarks": ["spy_buy_hold", "cash"],
            "caveats": ["fixture"],
        }
    )
    audit = AuditLog(tmp_path / "ops.sqlite", [])
    result = run_experiment(
        config,
        market_path=market,
        research_path=research,
        audit=audit,
    )
    return market, research, int(result["run_id"])


def test_replay_pass_on_untampered_run(tmp_path: Path) -> None:
    market, research, run_id = _seed(tmp_path)
    report = replay_run(run_id, research_path=research, market_path=market)
    assert report["verdict"] == "PASS"
    assert "checks_scope" in report


def test_replay_fails_when_decision_deleted(tmp_path: Path) -> None:
    market, research, run_id = _seed(tmp_path)
    with sqlite3.connect(research) as connection:
        row = connection.execute(
            """
            SELECT id FROM simulated_decisions
            WHERE run_id = ? AND strategy_id = 'spy_tsmom_12_1'
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        assert row is not None
        connection.execute("DELETE FROM simulated_decisions WHERE id = ?", (row[0],))
        connection.commit()
    report = replay_run(run_id, research_path=research, market_path=market)
    assert report["verdict"] == "FAIL"
    kinds = {item["kind"] for item in report["mismatches"]}  # type: ignore[index]
    assert "extra_recomputed_decision" in kinds or "decision_count_mismatch" in kinds


def test_replay_fails_when_equity_tampered(tmp_path: Path) -> None:
    market, research, run_id = _seed(tmp_path)
    with sqlite3.connect(research) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT id, equity FROM equity_points WHERE run_id = ? LIMIT 1", (run_id,)
        ).fetchone()
        assert row is not None
        connection.execute(
            "UPDATE equity_points SET equity = ? WHERE id = ?",
            (str(Decimal(row["equity"]) + Decimal("1")), row["id"]),
        )
        connection.commit()
    report = replay_run(run_id, research_path=research, market_path=market)
    assert report["verdict"] == "FAIL"
    kinds = {item["kind"] for item in report["mismatches"]}  # type: ignore[index]
    assert (
        "equity_point_mismatch" in kinds
        or "opening_equity_mismatch" in kinds
        or ("equity_cash_mismatch" in kinds)
    )


def test_replay_fails_when_metric_tampered(tmp_path: Path) -> None:
    market, research, run_id = _seed(tmp_path)
    with sqlite3.connect(research) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT id, metrics_json FROM run_metrics
            WHERE run_id = ? AND window = 'test' LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row["metrics_json"])
        payload["net_return"] = "0.999"
        connection.execute(
            "UPDATE run_metrics SET metrics_json = ? WHERE id = ?",
            (json.dumps(payload), row["id"]),
        )
        connection.commit()
    report = replay_run(run_id, research_path=research, market_path=market)
    assert report["verdict"] == "FAIL"
    kinds = {item["kind"] for item in report["mismatches"]}  # type: ignore[index]
    assert "metric_net_return_mismatch" in kinds
