"""Local approval inbox. Not a broker order store."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCOPE = "internal_shadow_simulation_only"

SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    instrument TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity TEXT NOT NULL,
    notional_usd TEXT NOT NULL,
    why TEXT NOT NULL,
    risk_summary TEXT NOT NULL,
    caveats TEXT NOT NULL,
    scope TEXT NOT NULL,
    broker_orders INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT,
    decision_reason TEXT NOT NULL DEFAULT '',
    preview_hash TEXT NOT NULL DEFAULT '',
    ledger_version INTEGER NOT NULL DEFAULT 0,
    policy_hash TEXT NOT NULL DEFAULT '',
    market_fingerprint TEXT NOT NULL DEFAULT '',
    proposal_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS approval_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    at TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


class ApprovalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._readonly = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            _migrate(conn)
            conn.commit()

    @classmethod
    def open_readonly(cls, path: str | Path) -> ApprovalStore | None:
        candidate = Path(path)
        if not candidate.is_file():
            return None
        store = cls.__new__(cls)
        store.path = candidate
        store._readonly = True
        return store

    def _connect(self) -> sqlite3.Connection:
        if self._readonly:
            conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert(self, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO approval_requests (
                    id, status, token_hash, instrument, action, quantity, notional_usd,
                    why, risk_summary, caveats, scope, broker_orders, created_at,
                    expires_at, decided_at, decision_reason,
                    preview_hash, ledger_version, policy_hash, market_fingerprint,
                    proposal_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["status"],
                    record["token_hash"],
                    record["instrument"],
                    record["action"],
                    record["quantity"],
                    record["notional_usd"],
                    record["why"],
                    record["risk_summary"],
                    record["caveats"],
                    record["scope"],
                    0,
                    record["created_at"],
                    record.get("expires_at"),
                    None,
                    "",
                    record.get("preview_hash") or "",
                    int(record.get("ledger_version") or 0),
                    record.get("policy_hash") or "",
                    record.get("market_fingerprint") or "",
                    record.get("proposal_id") or "",
                ),
            )
            self._audit(conn, record["id"], "created", "Internal shadow approval requested.")
            conn.commit()

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def pending_with_preview(self, preview_hash: str) -> dict[str, Any] | None:
        if not preview_hash:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM approval_requests
                WHERE preview_hash = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,
                (preview_hash,),
            ).fetchone()
        return None if row is None else dict(row)

    def pending_with_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        if not proposal_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM approval_requests
                WHERE proposal_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,
                (proposal_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def list_requests(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM approval_requests ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def audit_for(self, request_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT at, event, detail FROM approval_audit WHERE request_id = ? ORDER BY id",
                (request_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_audit(self, request_id: str, event: str, detail: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._audit(conn, request_id, event, detail)
            conn.commit()

    def decide(
        self,
        request_id: str,
        *,
        status: str,
        reason: str,
        now: datetime,
    ) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE approval_requests
                SET status = ?, decided_at = ?, decision_reason = ?
                WHERE id = ?
                """,
                (status, now.isoformat(), reason, request_id),
            )
            self._audit(conn, request_id, status, reason or status)
            conn.commit()

    def _audit(self, conn: sqlite3.Connection, request_id: str, event: str, detail: str) -> None:
        conn.execute(
            "INSERT INTO approval_audit (request_id, at, event, detail) VALUES (?, ?, ?, ?)",
            (request_id, datetime.now(UTC).isoformat(), event, detail[:500]),
        )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_view(row: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Drop the token hash and show expiry without writing."""
    status = str(row["status"])
    expires = datetime.fromisoformat(str(row["expires_at"]))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if status == "pending" and expires <= now:
        status = "expired"
    return {
        "id": row["id"],
        "status": status,
        "instrument": row["instrument"],
        "action": row["action"],
        "quantity": row["quantity"],
        "notional_usd": row["notional_usd"],
        "why": row["why"],
        "risk_summary": row["risk_summary"],
        "caveats": row["caveats"],
        "scope": SCOPE,
        "broker_orders": False,
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "decided_at": row["decided_at"],
        "decision_reason": row["decision_reason"],
        "preview_hash": row.get("preview_hash") or "",
        "ledger_version": row.get("ledger_version") or 0,
        "policy_hash": row.get("policy_hash") or "",
        "market_fingerprint": row.get("market_fingerprint") or "",
        "proposal_id": row.get("proposal_id") or "",
        "effect": "records_internal_shadow_permission_only",
    }


def _migrate(conn: sqlite3.Connection) -> None:
    have = {str(row[1]) for row in conn.execute("PRAGMA table_info(approval_requests)")}
    additions = {
        "preview_hash": "TEXT NOT NULL DEFAULT ''",
        "ledger_version": "INTEGER NOT NULL DEFAULT 0",
        "policy_hash": "TEXT NOT NULL DEFAULT ''",
        "market_fingerprint": "TEXT NOT NULL DEFAULT ''",
        "proposal_id": "TEXT NOT NULL DEFAULT ''",
    }
    for name, declaration in additions.items():
        if name not in have:
            conn.execute(f"ALTER TABLE approval_requests ADD COLUMN {name} {declaration}")
