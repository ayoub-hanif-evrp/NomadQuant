"""Persistent $100 shadow portfolio and cycle history. Never touches Alpaca."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_ledger (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL,
    cash_usd TEXT NOT NULL,
    reserved_cash_usd TEXT NOT NULL,
    holdings_json TEXT NOT NULL,
    cost_basis_json TEXT NOT NULL,
    realized_pnl_usd TEXT NOT NULL,
    total_costs_usd TEXT NOT NULL,
    peak_equity_usd TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    label TEXT NOT NULL,
    signal_session TEXT,
    fill_session TEXT,
    feed TEXT NOT NULL,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    intent TEXT NOT NULL,
    target_weight TEXT,
    momentum TEXT,
    proposal_id TEXT,
    risk_verdict TEXT,
    risk_reasons_json TEXT NOT NULL,
    fill_price TEXT,
    fill_qty TEXT,
    fill_side TEXT,
    costs_usd TEXT,
    evidence_json TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    error_safe TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL,
    ledger_before_json TEXT NOT NULL,
    ledger_after_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS shadow_cycles_created ON shadow_cycles (created_at DESC);
CREATE TABLE IF NOT EXISTS shadow_equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER,
    recorded_at TEXT NOT NULL,
    session TEXT,
    equity_usd TEXT NOT NULL,
    cash_usd TEXT NOT NULL,
    exposure_usd TEXT NOT NULL,
    realized_pnl_usd TEXT NOT NULL,
    unrealized_pnl_usd TEXT NOT NULL,
    FOREIGN KEY (cycle_id) REFERENCES shadow_cycles(id)
);
"""


class ShadowStoreError(ValueError):
    pass


class ShadowStore:
    def __init__(self, path: str | Path = "data/shadow.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            row = conn.execute("SELECT id FROM shadow_ledger WHERE id = 1").fetchone()
            if row is None:
                now = datetime.now(UTC).isoformat()
                conn.execute(
                    """
                    INSERT INTO shadow_ledger (
                        id, version, cash_usd, reserved_cash_usd, holdings_json,
                        cost_basis_json, realized_pnl_usd, total_costs_usd,
                        peak_equity_usd, updated_at
                    ) VALUES (1, 1, '100', '0', '{}', '{}', '0', '0', '100', ?)
                    """,
                    (now,),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO shadow_meta (key, value) "
                    "VALUES ('starting_capital', '100')"
                )
                conn.commit()

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM shadow_ledger WHERE id = 1").fetchone()
        assert row is not None
        holdings = json.loads(row["holdings_json"])
        basis = json.loads(row["cost_basis_json"])
        return {
            "version": row["version"],
            "cash_usd": Decimal(row["cash_usd"]),
            "reserved_cash_usd": Decimal(row["reserved_cash_usd"]),
            "holdings": {k: Decimal(v) for k, v in holdings.items()},
            "cost_basis": {k: Decimal(v) for k, v in basis.items()},
            "realized_pnl_usd": Decimal(row["realized_pnl_usd"]),
            "total_costs_usd": Decimal(row["total_costs_usd"]),
            "peak_equity_usd": Decimal(row["peak_equity_usd"]),
            "updated_at": row["updated_at"],
            "starting_capital_usd": Decimal("100"),
        }

    def cycle_exists(self, cycle_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM shadow_cycles WHERE cycle_key = ?", (cycle_key,)
            ).fetchone()
        return row is not None

    def get_cycle(self, cycle_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM shadow_cycles WHERE id = ?", (cycle_id,)).fetchone()
        return None if row is None else _cycle_row(row)

    def get_cycle_by_key(self, cycle_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM shadow_cycles WHERE cycle_key = ?", (cycle_key,)
            ).fetchone()
        return None if row is None else _cycle_row(row)

    def list_cycles(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM shadow_cycles ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_cycle_row(row) for row in rows]

    def count_cycles(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM shadow_cycles").fetchone()
        return int(row["n"])

    def equity_history(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM shadow_equity ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "cycle_id": row["cycle_id"],
                "recorded_at": row["recorded_at"],
                "session": row["session"],
                "equity_usd": row["equity_usd"],
                "cash_usd": row["cash_usd"],
                "exposure_usd": row["exposure_usd"],
                "realized_pnl_usd": row["realized_pnl_usd"],
                "unrealized_pnl_usd": row["unrealized_pnl_usd"],
            }
            for row in rows
        ]

    def apply_cycle(
        self,
        *,
        cycle_key: str,
        payload: dict[str, Any],
        ledger_after: dict[str, Any] | None,
        equity_point: dict[str, Any] | None,
    ) -> int:
        """Atomically insert cycle (+ optional ledger mutation and equity point)."""
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute(
                    "SELECT 1 FROM shadow_cycles WHERE cycle_key = ?", (cycle_key,)
                ).fetchone():
                    raise ShadowStoreError(f"Duplicate cycle_key {cycle_key!r}.")
                cur = conn.execute(
                    """
                    INSERT INTO shadow_cycles (
                        cycle_key, created_at, mode, label, signal_session, fill_session,
                        feed, symbol, status, intent, target_weight, momentum, proposal_id,
                        risk_verdict, risk_reasons_json, fill_price, fill_qty, fill_side,
                        costs_usd, evidence_json, evidence_hash, warnings_json, error_safe,
                        duration_ms, ledger_before_json, ledger_after_json
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        cycle_key,
                        payload["created_at"],
                        payload["mode"],
                        payload["label"],
                        payload.get("signal_session"),
                        payload.get("fill_session"),
                        payload["feed"],
                        payload["symbol"],
                        payload["status"],
                        payload["intent"],
                        payload.get("target_weight"),
                        payload.get("momentum"),
                        payload.get("proposal_id"),
                        payload.get("risk_verdict"),
                        json.dumps(payload.get("risk_reasons") or []),
                        payload.get("fill_price"),
                        payload.get("fill_qty"),
                        payload.get("fill_side"),
                        payload.get("costs_usd"),
                        json.dumps(payload.get("evidence") or {}),
                        payload["evidence_hash"],
                        json.dumps(payload.get("warnings") or []),
                        payload.get("error_safe") or "",
                        int(payload.get("duration_ms") or 0),
                        json.dumps(payload["ledger_before"], default=str),
                        json.dumps(
                            payload.get("ledger_after") or payload["ledger_before"], default=str
                        ),
                    ),
                )
                cycle_id = int(cur.lastrowid or 0)
                if ledger_after is not None:
                    conn.execute(
                        """
                        UPDATE shadow_ledger SET
                            version = version + 1,
                            cash_usd = ?,
                            reserved_cash_usd = ?,
                            holdings_json = ?,
                            cost_basis_json = ?,
                            realized_pnl_usd = ?,
                            total_costs_usd = ?,
                            peak_equity_usd = ?,
                            updated_at = ?
                        WHERE id = 1
                        """,
                        (
                            str(ledger_after["cash_usd"]),
                            str(ledger_after["reserved_cash_usd"]),
                            json.dumps({k: str(v) for k, v in ledger_after["holdings"].items()}),
                            json.dumps({k: str(v) for k, v in ledger_after["cost_basis"].items()}),
                            str(ledger_after["realized_pnl_usd"]),
                            str(ledger_after["total_costs_usd"]),
                            str(ledger_after["peak_equity_usd"]),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                if equity_point is not None:
                    conn.execute(
                        """
                        INSERT INTO shadow_equity (
                            cycle_id, recorded_at, session, equity_usd, cash_usd,
                            exposure_usd, realized_pnl_usd, unrealized_pnl_usd
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cycle_id,
                            equity_point["recorded_at"],
                            equity_point.get("session"),
                            str(equity_point["equity_usd"]),
                            str(equity_point["cash_usd"]),
                            str(equity_point["exposure_usd"]),
                            str(equity_point["realized_pnl_usd"]),
                            str(equity_point["unrealized_pnl_usd"]),
                        ),
                    )
                conn.commit()
                return cycle_id
            except Exception:
                conn.rollback()
                raise

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def _cycle_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "cycle_key": row["cycle_key"],
        "created_at": row["created_at"],
        "mode": row["mode"],
        "label": row["label"],
        "signal_session": row["signal_session"],
        "fill_session": row["fill_session"],
        "feed": row["feed"],
        "symbol": row["symbol"],
        "status": row["status"],
        "intent": row["intent"],
        "target_weight": row["target_weight"],
        "momentum": row["momentum"],
        "proposal_id": row["proposal_id"],
        "risk_verdict": row["risk_verdict"],
        "risk_reasons": json.loads(row["risk_reasons_json"]),
        "fill_price": row["fill_price"],
        "fill_qty": row["fill_qty"],
        "fill_side": row["fill_side"],
        "costs_usd": row["costs_usd"],
        "evidence": json.loads(row["evidence_json"]),
        "evidence_hash": row["evidence_hash"],
        "warnings": json.loads(row["warnings_json"]),
        "error_safe": row["error_safe"],
        "duration_ms": row["duration_ms"],
        "ledger_before": json.loads(row["ledger_before_json"]),
        "ledger_after": json.loads(row["ledger_after_json"]),
    }
