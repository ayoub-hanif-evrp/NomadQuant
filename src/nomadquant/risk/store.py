"""Append-only risk evaluations with transactional proposal reservations.

``reserve`` / ``record`` / ``release_reservation`` separate durable idempotency
from pure evaluation. A reservation is not an executed order.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.risk.schemas import EvaluationResult, Proposal

SCHEMA = """
CREATE TABLE IF NOT EXISTS risk_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity TEXT NOT NULL,
    limit_price TEXT,
    proposal_as_of TEXT NOT NULL,
    agent_run_id INTEGER,
    verdict TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    rule_verdicts_json TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    policy_hash TEXT NOT NULL,
    notional_usd TEXT,
    projected_cash_usd TEXT,
    evaluated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS risk_evaluations_created ON risk_evaluations (created_at);

CREATE TABLE IF NOT EXISTS risk_reservations (
    proposal_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    reserved_cash_usd TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity TEXT NOT NULL,
    expires_at TEXT,
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS risk_reservations_status ON risk_reservations (status);
"""


class RiskStoreError(ValueError):
    """A write would overwrite an immutable evaluation or reservation."""


class RiskStore:
    def __init__(self, path: str | Path = "data/risk.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def seen(self, proposal_id: str) -> bool:
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM risk_evaluations WHERE proposal_id = ?", (proposal_id,)
            ).fetchone():
                return True
            row = connection.execute(
                "SELECT status FROM risk_reservations WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return row is not None and row["status"] in {"reserved", "committed"}

    def reserve(
        self,
        proposal: Proposal,
        *,
        reserved_cash_usd: Decimal,
        expires_at: datetime | None = None,
    ) -> None:
        """Transactionally claim a proposal id. Concurrent callers: one wins."""
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT 1 FROM risk_evaluations WHERE proposal_id = ?", (proposal.id,)
                ).fetchone():
                    raise RiskStoreError(f"Proposal {proposal.id!r} already evaluated.")
                existing = connection.execute(
                    "SELECT status FROM risk_reservations WHERE proposal_id = ?",
                    (proposal.id,),
                ).fetchone()
                if existing is not None and existing["status"] in {"reserved", "committed"}:
                    raise RiskStoreError(f"Proposal {proposal.id!r} already reserved.")
                connection.execute(
                    """
                    INSERT INTO risk_reservations (
                        proposal_id, created_at, status, reserved_cash_usd,
                        symbol, side, quantity, expires_at, note
                    ) VALUES (?, ?, 'reserved', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(proposal_id) DO UPDATE SET
                        status='reserved',
                        created_at=excluded.created_at,
                        reserved_cash_usd=excluded.reserved_cash_usd,
                        expires_at=excluded.expires_at
                    WHERE risk_reservations.status NOT IN ('reserved', 'committed')
                    """,
                    (
                        proposal.id,
                        _now(),
                        str(reserved_cash_usd),
                        proposal.symbol,
                        proposal.side,
                        str(proposal.quantity),
                        None if expires_at is None else expires_at.isoformat(),
                        "cash reservation only; not a broker order",
                    ),
                )
                row = connection.execute(
                    "SELECT status FROM risk_reservations WHERE proposal_id = ?",
                    (proposal.id,),
                ).fetchone()
                if row is None or row["status"] != "reserved":
                    raise RiskStoreError(f"Could not reserve proposal {proposal.id!r}.")
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def release_reservation(self, proposal_id: str, *, reason: str = "released") -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE risk_reservations
                SET status = 'released', note = ?
                WHERE proposal_id = ? AND status = 'reserved'
                """,
                (reason, proposal_id),
            )
            connection.commit()

    def commit_reservation(self, proposal_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE risk_reservations
                SET status = 'committed', note = 'linked to simulated or future execution'
                WHERE proposal_id = ? AND status = 'reserved'
                """,
                (proposal_id,),
            )
            connection.commit()

    def record(self, proposal: Proposal, result: EvaluationResult) -> int:
        if proposal.id != result.proposal_id:
            raise RiskStoreError("Proposal id does not match the evaluation result.")
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT 1 FROM risk_evaluations WHERE proposal_id = ?", (proposal.id,)
                ).fetchone():
                    raise RiskStoreError(
                        f"Proposal {proposal.id!r} was already recorded and cannot be overwritten."
                    )
                cursor = connection.execute(
                    """
                    INSERT INTO risk_evaluations (
                        proposal_id, created_at, source, symbol, side, quantity,
                        limit_price, proposal_as_of, agent_run_id, verdict, reasons_json,
                        rule_verdicts_json, policy_version, policy_hash, notional_usd,
                        projected_cash_usd, evaluated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal.id,
                        _now(),
                        proposal.source,
                        proposal.symbol,
                        proposal.side,
                        str(proposal.quantity),
                        None if proposal.limit_price is None else str(proposal.limit_price),
                        proposal.as_of.isoformat(),
                        proposal.agent_run_id,
                        result.verdict,
                        json.dumps(result.reasons),
                        json.dumps([rv.model_dump() for rv in result.rule_verdicts], default=str),
                        result.policy_version,
                        result.policy_hash,
                        None if result.notional_usd is None else str(result.notional_usd),
                        None
                        if result.projected_cash_usd is None
                        else str(result.projected_cash_usd),
                        result.evaluated_at.isoformat(),
                    ),
                )
                connection.commit()
                return int(cursor.lastrowid or 0)
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise RiskStoreError(
                    f"Proposal {proposal.id!r} was already recorded and cannot be overwritten."
                ) from exc
            except Exception:
                connection.rollback()
                raise

    def get(self, proposal_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM risk_evaluations WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        return None if row is None else _row(row)

    def get_by_id(self, evaluation_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM risk_evaluations WHERE id = ?", (evaluation_id,)
            ).fetchone()
        return None if row is None else _row(row)

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM risk_evaluations ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_row(row) for row in rows]

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM risk_evaluations").fetchone()
        return int(row["n"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "proposal_id": row["proposal_id"],
        "created_at": row["created_at"],
        "source": row["source"],
        "symbol": row["symbol"],
        "side": row["side"],
        "quantity": row["quantity"],
        "limit_price": row["limit_price"],
        "proposal_as_of": row["proposal_as_of"],
        "agent_run_id": row["agent_run_id"],
        "verdict": row["verdict"],
        "reasons": json.loads(row["reasons_json"]),
        "rule_verdicts": json.loads(row["rule_verdicts_json"]),
        "policy_version": row["policy_version"],
        "policy_hash": row["policy_hash"],
        "notional_usd": row["notional_usd"],
        "projected_cash_usd": row["projected_cash_usd"],
        "evaluated_at": row["evaluated_at"],
    }
