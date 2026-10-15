"""SQLite registry for experiments, runs, equity, trades, and decisions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    hypothesis_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    citations_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    git_commit TEXT,
    engine_version TEXT NOT NULL,
    dataset_fingerprint TEXT NOT NULL,
    config_json TEXT NOT NULL,
    audit_run_id INTEGER,
    outcome_summary TEXT NOT NULL,
    caveats_json TEXT NOT NULL,
    error_code TEXT NOT NULL,
    error_message_safe TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);
CREATE TABLE IF NOT EXISTS run_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    strategy_id TEXT NOT NULL,
    window TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES experiment_runs(id)
);
CREATE TABLE IF NOT EXISTS equity_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    strategy_id TEXT NOT NULL,
    session_date TEXT NOT NULL,
    equity TEXT NOT NULL,
    cash TEXT NOT NULL,
    exposure TEXT NOT NULL,
    drawdown TEXT NOT NULL,
    window TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES experiment_runs(id)
);
CREATE TABLE IF NOT EXISTS simulated_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    strategy_id TEXT NOT NULL,
    session_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity TEXT NOT NULL,
    price TEXT NOT NULL,
    notional TEXT NOT NULL,
    commission TEXT NOT NULL,
    spread_cost TEXT NOT NULL,
    slippage_cost TEXT NOT NULL,
    reason TEXT NOT NULL,
    is_simulated INTEGER NOT NULL DEFAULT 1,
    is_broker_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES experiment_runs(id)
);
CREATE TABLE IF NOT EXISTS simulated_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    strategy_id TEXT NOT NULL,
    session_date TEXT NOT NULL,
    decision_timestamp TEXT NOT NULL,
    data_cutoff TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signal TEXT NOT NULL,
    feature_inputs_json TEXT NOT NULL,
    proposed_target_weight TEXT NOT NULL,
    action TEXT NOT NULL,
    rationale TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    fill_session TEXT,
    fill_price TEXT,
    portfolio_before_json TEXT NOT NULL,
    portfolio_after_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    is_simulated INTEGER NOT NULL DEFAULT 1,
    is_broker_order INTEGER NOT NULL DEFAULT 0,
    audit_decision_id INTEGER,
    FOREIGN KEY (run_id) REFERENCES experiment_runs(id)
);
CREATE INDEX IF NOT EXISTS experiment_runs_exp ON experiment_runs (experiment_id);
CREATE INDEX IF NOT EXISTS decisions_run ON simulated_decisions (run_id, session_date);
"""


class ResearchStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def upsert_experiment(self, row: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO experiments (
                    experiment_id, hypothesis_id, title, description, citations_json,
                    config_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    citations_json=excluded.citations_json,
                    config_json=excluded.config_json
                """,
                (
                    row["experiment_id"],
                    row["hypothesis_id"],
                    row["title"],
                    row["description"],
                    json.dumps(row["citations"]),
                    json.dumps(row["config"]),
                    row["created_at"],
                ),
            )

    def start_run(self, row: dict[str, Any]) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO experiment_runs (
                    experiment_id, created_at, finished_at, status, git_commit,
                    engine_version, dataset_fingerprint, config_json, audit_run_id,
                    outcome_summary, caveats_json, error_code, error_message_safe
                ) VALUES (?, ?, NULL, 'started', ?, ?, ?, ?, ?, '', '[]', '', '')
                """,
                (
                    row["experiment_id"],
                    row["created_at"],
                    row.get("git_commit"),
                    row["engine_version"],
                    row["dataset_fingerprint"],
                    json.dumps(row["config"]),
                    row.get("audit_run_id"),
                ),
            )
            return int(cursor.lastrowid or 0)

    def finish_run(self, run_id: int, row: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE experiment_runs
                SET finished_at = ?, status = ?, outcome_summary = ?, caveats_json = ?,
                    error_code = ?, error_message_safe = ?
                WHERE id = ?
                """,
                (
                    row["finished_at"],
                    row["status"],
                    row["outcome_summary"],
                    json.dumps(row.get("caveats", [])),
                    row.get("error_code", ""),
                    row.get("error_message_safe", ""),
                    run_id,
                ),
            )

    def save_strategy_result(self, run_id: int, strategy_id: str, result: dict[str, Any]) -> None:
        with self._connect() as connection:
            for metrics in result["metrics"]:
                connection.execute(
                    """
                    INSERT INTO run_metrics (run_id, strategy_id, window, metrics_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (run_id, strategy_id, metrics["window"], json.dumps(metrics)),
                )
            for point in result["equity"]:
                connection.execute(
                    """
                    INSERT INTO equity_points (
                        run_id, strategy_id, session_date, equity, cash, exposure,
                        drawdown, window
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        strategy_id,
                        point["session_date"],
                        point["equity"],
                        point["cash"],
                        point["exposure"],
                        point["drawdown"],
                        point["window"],
                    ),
                )
            for trade in result["trades"]:
                connection.execute(
                    """
                    INSERT INTO simulated_trades (
                        run_id, strategy_id, session_date, symbol, side, quantity, price,
                        notional, commission, spread_cost, slippage_cost, reason,
                        is_simulated, is_broker_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                    """,
                    (
                        run_id,
                        strategy_id,
                        trade["session_date"],
                        trade["symbol"],
                        trade["side"],
                        trade["quantity"],
                        trade["price"],
                        trade["notional"],
                        trade["commission"],
                        trade["spread_cost"],
                        trade["slippage_cost"],
                        trade["reason"],
                    ),
                )
            for decision in result["decisions"]:
                connection.execute(
                    """
                    INSERT INTO simulated_decisions (
                        run_id, strategy_id, session_date, decision_timestamp, data_cutoff,
                        symbol, signal, feature_inputs_json, proposed_target_weight, action,
                        rationale, evidence_hash, fill_session, fill_price,
                        portfolio_before_json, portfolio_after_json, warnings_json,
                        is_simulated, is_broker_order, audit_decision_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)
                    """,
                    (
                        run_id,
                        strategy_id,
                        decision["session_date"],
                        decision["decision_timestamp"],
                        decision["data_cutoff"],
                        decision["symbol"],
                        decision["signal"],
                        json.dumps(decision["feature_inputs"]),
                        decision["proposed_target_weight"],
                        decision["action"],
                        decision["rationale"],
                        decision["evidence_hash"],
                        decision.get("fill_session"),
                        decision.get("fill_price"),
                        json.dumps(decision["portfolio_before"]),
                        json.dumps(decision["portfolio_after"]),
                        json.dumps(decision.get("warnings", [])),
                        decision.get("audit_decision_id"),
                    ),
                )

    def list_experiments(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM experiments ORDER BY created_at DESC"
            ).fetchall()
        return [_experiment(row) for row in rows]

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
        return None if row is None else _experiment(row)

    def list_runs(self, experiment_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if experiment_id:
                rows = connection.execute(
                    """
                    SELECT * FROM experiment_runs
                    WHERE experiment_id = ?
                    ORDER BY id DESC
                    """,
                    (experiment_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM experiment_runs ORDER BY id DESC"
                ).fetchall()
        return [_run(row) for row in rows]

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM experiment_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return None if row is None else _run(row)

    def metrics(self, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM run_metrics WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        return [
            {
                "strategy_id": row["strategy_id"],
                "window": row["window"],
                **json.loads(row["metrics_json"]),
            }
            for row in rows
        ]

    def equity(self, run_id: int, strategy_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM equity_points WHERE run_id = ?"
        params: list[object] = [run_id]
        if strategy_id:
            query += " AND strategy_id = ?"
            params.append(strategy_id)
        query += " ORDER BY session_date, strategy_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "strategy_id": row["strategy_id"],
                "session_date": row["session_date"],
                "equity": row["equity"],
                "cash": row["cash"],
                "exposure": row["exposure"],
                "drawdown": row["drawdown"],
                "window": row["window"],
            }
            for row in rows
        ]

    def trades(self, run_id: int, strategy_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM simulated_trades WHERE run_id = ?"
        params: list[object] = [run_id]
        if strategy_id:
            query += " AND strategy_id = ?"
            params.append(strategy_id)
        query += " ORDER BY session_date, id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_trade(row) for row in rows]

    def decisions(self, run_id: int, strategy_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM simulated_decisions WHERE run_id = ?"
        params: list[object] = [run_id]
        if strategy_id:
            query += " AND strategy_id = ?"
            params.append(strategy_id)
        query += " ORDER BY session_date, id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_decision(row) for row in rows]

    def get_decision(self, decision_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM simulated_decisions WHERE id = ?", (decision_id,)
            ).fetchone()
        return None if row is None else _decision(row)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def _experiment(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "experiment_id": row["experiment_id"],
        "hypothesis_id": row["hypothesis_id"],
        "title": row["title"],
        "description": row["description"],
        "citations": json.loads(row["citations_json"]),
        "config": json.loads(row["config_json"]),
        "created_at": row["created_at"],
    }


def _run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "experiment_id": row["experiment_id"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
        "status": row["status"],
        "git_commit": row["git_commit"],
        "engine_version": row["engine_version"],
        "dataset_fingerprint": row["dataset_fingerprint"],
        "config": json.loads(row["config_json"]),
        "audit_run_id": row["audit_run_id"],
        "outcome_summary": row["outcome_summary"],
        "caveats": json.loads(row["caveats_json"]),
        "error_code": row["error_code"],
        "error_message_safe": row["error_message_safe"],
        "label": "backtest",
        "is_paper_trading": False,
        "is_broker_execution": False,
    }


def _trade(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "strategy_id": row["strategy_id"],
        "session_date": row["session_date"],
        "symbol": row["symbol"],
        "side": row["side"],
        "quantity": row["quantity"],
        "price": row["price"],
        "notional": row["notional"],
        "commission": row["commission"],
        "spread_cost": row["spread_cost"],
        "slippage_cost": row["slippage_cost"],
        "reason": row["reason"],
        "is_simulated": True,
        "is_broker_order": False,
    }


def _decision(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "strategy_id": row["strategy_id"],
        "session_date": row["session_date"],
        "decision_timestamp": row["decision_timestamp"],
        "data_cutoff": row["data_cutoff"],
        "symbol": row["symbol"],
        "signal": row["signal"],
        "feature_inputs": json.loads(row["feature_inputs_json"]),
        "proposed_target_weight": row["proposed_target_weight"],
        "action": row["action"],
        "rationale": row["rationale"],
        "evidence_hash": row["evidence_hash"],
        "fill_session": row["fill_session"],
        "fill_price": row["fill_price"],
        "portfolio_before": json.loads(row["portfolio_before_json"]),
        "portfolio_after": json.loads(row["portfolio_after_json"]),
        "warnings": json.loads(row["warnings_json"]),
        "is_simulated": True,
        "is_broker_order": False,
        "audit_decision_id": row["audit_decision_id"],
    }
