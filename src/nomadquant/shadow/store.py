"""Persistent $100 shadow portfolio. Forward and retrospective are isolated DBs."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

Namespace = Literal["forward", "retrospective", "test"]

LABEL_FORWARD = "forward_shadow"
LABEL_RETRO = "retrospective_replay"

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
CREATE TABLE IF NOT EXISTS shadow_intents (
    intent_id TEXT PRIMARY KEY,
    cycle_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    signal_session TEXT,
    fill_session TEXT,
    feed TEXT NOT NULL,
    symbol TEXT NOT NULL,
    target_weight TEXT,
    evidence_json TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_reservations (
    intent_id TEXT PRIMARY KEY,
    cycle_key TEXT NOT NULL,
    reserved_cash_usd TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (intent_id) REFERENCES shadow_intents(intent_id)
);
CREATE TABLE IF NOT EXISTS shadow_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    dataset_feed TEXT,
    signal_session TEXT,
    observation_cutoff TEXT,
    source_price TEXT,
    price_as_of TEXT,
    risk_verdict TEXT,
    ledger_version_before INTEGER,
    ledger_version_after INTEGER,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS shadow_transitions_intent ON shadow_transitions (intent_id, id);
CREATE TABLE IF NOT EXISTS shadow_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    projected_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT ''
);
"""


class ShadowStoreError(ValueError):
    pass


class ConcurrentModificationError(ShadowStoreError):
    pass


def shadow_path_for_label(base: str | Path, label: str) -> Path:
    """Physically separate forward vs retrospective ledgers."""
    base_path = Path(base)
    if label == LABEL_FORWARD:
        return base_path
    if label == LABEL_RETRO:
        return base_path.with_name(base_path.stem + "_retrospective" + base_path.suffix)
    raise ValueError(f"Unknown label {label!r}")


def namespace_for_label(label: str) -> Namespace:
    if label == LABEL_FORWARD:
        return "forward"
    if label == LABEL_RETRO:
        return "retrospective"
    raise ValueError(f"Unknown label {label!r}")


class ShadowStore:
    def __init__(
        self,
        path: str | Path = "data/shadow.sqlite",
        *,
        namespace: Namespace = "forward",
    ) -> None:
        self.namespace = namespace
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            _ensure_outbox_columns(conn)
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
                conn.execute(
                    "INSERT OR REPLACE INTO shadow_meta (key, value) VALUES ('namespace', ?)",
                    (namespace,),
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
            "namespace": self.namespace,
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

    def list_cycles(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM shadow_cycles WHERE status = ? "
                    "ORDER BY id DESC LIMIT ? OFFSET ?",
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM shadow_cycles ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        return [_cycle_row(row) for row in rows]

    def count_cycles(self, *, status: str | None = None) -> int:
        with self._connect() as conn:
            if status:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM shadow_cycles WHERE status = ?",
                    (status,),
                ).fetchone()
            else:
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

    def apply_ledger_mutation(
        self,
        *,
        expected_version: int,
        ledger_after: dict[str, Any],
    ) -> int:
        """Version-aware conditional ledger update (OCC)."""
        _validate_ledger(ledger_after)
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                new_version = self._update_ledger_occ(conn, expected_version, ledger_after)
                conn.commit()
                return new_version
            except Exception:
                conn.rollback()
                raise

    def reserve_cash(
        self,
        *,
        intent_id: str,
        amount: Decimal,
        expected_version: int,
        cycle_key: str,
    ) -> int:
        if amount < 0:
            raise ValueError("Reservation amount cannot be negative.")
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                snap = _ledger_row(conn)
                if int(snap["version"]) != expected_version:
                    raise ConcurrentModificationError(
                        f"Stale ledger version {expected_version}; current is {snap['version']}."
                    )
                cash = Decimal(snap["cash_usd"])
                reserved = Decimal(snap["reserved_cash_usd"])
                available = cash - reserved
                if amount > available:
                    raise ShadowStoreError(
                        f"Insufficient available cash: need {amount}, have {available}."
                    )
                new_reserved = reserved + amount
                after = {
                    "cash_usd": cash,
                    "reserved_cash_usd": new_reserved,
                    "holdings": {
                        k: Decimal(v) for k, v in json.loads(snap["holdings_json"]).items()
                    },
                    "cost_basis": {
                        k: Decimal(v) for k, v in json.loads(snap["cost_basis_json"]).items()
                    },
                    "realized_pnl_usd": Decimal(snap["realized_pnl_usd"]),
                    "total_costs_usd": Decimal(snap["total_costs_usd"]),
                    "peak_equity_usd": Decimal(snap["peak_equity_usd"]),
                }
                new_version = self._update_ledger_occ(conn, expected_version, after)
                conn.execute(
                    """
                    INSERT INTO shadow_reservations (
                        intent_id, cycle_key, reserved_cash_usd, status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'active', ?, ?)
                    ON CONFLICT(intent_id) DO UPDATE SET
                        reserved_cash_usd = excluded.reserved_cash_usd,
                        status = 'active',
                        updated_at = excluded.updated_at
                    """,
                    (intent_id, cycle_key, str(amount), now, now),
                )
                conn.execute(
                    """
                    INSERT INTO shadow_intents (
                        intent_id, cycle_key, state, strategy_id, signal_session, fill_session,
                        feed, symbol, target_weight, evidence_json, evidence_hash,
                        created_at, updated_at
                    ) VALUES (?, ?, 'RESERVED', 'spy_tsmom_12_1', NULL, NULL, 'sip', 'SPY',
                              NULL, '{}', '', ?, ?)
                    ON CONFLICT(intent_id) DO UPDATE SET
                        state = 'RESERVED', updated_at = excluded.updated_at
                    """,
                    (intent_id, cycle_key, now, now),
                )
                self._append_transition(
                    conn,
                    intent_id=intent_id,
                    from_state="RISK_APPROVED",
                    to_state="RESERVED",
                    evidence_hash="",
                    reason=f"Reserved {amount} USD",
                    ledger_before=expected_version,
                    ledger_after=new_version,
                )
                conn.commit()
                return new_version
            except Exception:
                conn.rollback()
                raise

    def release_reservation(self, intent_id: str, *, expected_version: int) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM shadow_reservations WHERE intent_id = ?",
                    (intent_id,),
                ).fetchone()
                if row is None or row["status"] != "active":
                    conn.commit()
                    return expected_version
                amount = Decimal(row["reserved_cash_usd"])
                snap = _ledger_row(conn)
                if int(snap["version"]) != expected_version:
                    raise ConcurrentModificationError(
                        f"Stale ledger version {expected_version}; current is {snap['version']}."
                    )
                reserved = Decimal(snap["reserved_cash_usd"])
                new_reserved = max(Decimal("0"), reserved - amount)
                after = {
                    "cash_usd": Decimal(snap["cash_usd"]),
                    "reserved_cash_usd": new_reserved,
                    "holdings": {
                        k: Decimal(v) for k, v in json.loads(snap["holdings_json"]).items()
                    },
                    "cost_basis": {
                        k: Decimal(v) for k, v in json.loads(snap["cost_basis_json"]).items()
                    },
                    "realized_pnl_usd": Decimal(snap["realized_pnl_usd"]),
                    "total_costs_usd": Decimal(snap["total_costs_usd"]),
                    "peak_equity_usd": Decimal(snap["peak_equity_usd"]),
                }
                new_version = self._update_ledger_occ(conn, expected_version, after)
                conn.execute(
                    "UPDATE shadow_reservations SET status = 'released', updated_at = ? "
                    "WHERE intent_id = ? AND status = 'active'",
                    (now, intent_id),
                )
                self._append_transition(
                    conn,
                    intent_id=intent_id,
                    from_state="RESERVED",
                    to_state="CANCELLED",
                    evidence_hash="",
                    reason="Reservation released exactly once",
                    ledger_before=expected_version,
                    ledger_after=new_version,
                )
                conn.commit()
                return new_version
            except Exception:
                conn.rollback()
                raise

    def list_active_reservations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM shadow_reservations WHERE status = 'active'"
            ).fetchall()
        return [
            {
                "intent_id": r["intent_id"],
                "cycle_key": r["cycle_key"],
                "reserved_cash_usd": r["reserved_cash_usd"],
                "status": r["status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def recover_interrupted(self) -> dict[str, Any]:
        """Release active reservations without a completed fill (crash recovery)."""
        released: list[str] = []
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    "SELECT * FROM shadow_reservations WHERE status = 'active'"
                ).fetchall()
                for row in rows:
                    intent_id = row["intent_id"]
                    # Filled intents have SIMULATED_FILLED state — leave committed.
                    intent = conn.execute(
                        "SELECT state FROM shadow_intents WHERE intent_id = ?",
                        (intent_id,),
                    ).fetchone()
                    if intent is not None and intent["state"] == "SIMULATED_FILLED":
                        conn.execute(
                            "UPDATE shadow_reservations SET status = 'committed', "
                            "updated_at = ? WHERE intent_id = ?",
                            (datetime.now(UTC).isoformat(), intent_id),
                        )
                        continue
                    amount = Decimal(row["reserved_cash_usd"])
                    snap = _ledger_row(conn)
                    expected = int(snap["version"])
                    reserved = Decimal(snap["reserved_cash_usd"])
                    after = {
                        "cash_usd": Decimal(snap["cash_usd"]),
                        "reserved_cash_usd": max(Decimal("0"), reserved - amount),
                        "holdings": {
                            k: Decimal(v) for k, v in json.loads(snap["holdings_json"]).items()
                        },
                        "cost_basis": {
                            k: Decimal(v) for k, v in json.loads(snap["cost_basis_json"]).items()
                        },
                        "realized_pnl_usd": Decimal(snap["realized_pnl_usd"]),
                        "total_costs_usd": Decimal(snap["total_costs_usd"]),
                        "peak_equity_usd": Decimal(snap["peak_equity_usd"]),
                    }
                    new_v = self._update_ledger_occ(conn, expected, after)
                    now = datetime.now(UTC).isoformat()
                    conn.execute(
                        "UPDATE shadow_reservations SET status = 'released', updated_at = ? "
                        "WHERE intent_id = ? AND status = 'active'",
                        (now, intent_id),
                    )
                    self._append_transition(
                        conn,
                        intent_id=intent_id,
                        from_state="RESERVED",
                        to_state="FAILED",
                        evidence_hash="",
                        reason="Recovered interrupted reservation",
                        ledger_before=expected,
                        ledger_after=new_v,
                    )
                    released.append(intent_id)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"released_intent_ids": released}

    def apply_cycle(
        self,
        *,
        cycle_key: str,
        payload: dict[str, Any],
        ledger_after: dict[str, Any] | None,
        equity_point: dict[str, Any] | None,
        expected_version: int | None = None,
        commit_reservation_intent_id: str | None = None,
    ) -> int:
        """Atomically insert cycle (+ optional OCC ledger mutation and equity)."""
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
                            payload.get("ledger_after") or payload["ledger_before"],
                            default=str,
                        ),
                    ),
                )
                cycle_id = int(cur.lastrowid or 0)
                if ledger_after is not None:
                    if expected_version is None:
                        raise ShadowStoreError("expected_version required for ledger mutations.")
                    _validate_ledger(ledger_after)
                    self._update_ledger_occ(conn, expected_version, ledger_after)
                    if commit_reservation_intent_id:
                        conn.execute(
                            "UPDATE shadow_reservations SET status = 'committed', "
                            "updated_at = ? WHERE intent_id = ?",
                            (
                                datetime.now(UTC).isoformat(),
                                commit_reservation_intent_id,
                            ),
                        )
                        conn.execute(
                            "UPDATE shadow_intents SET state = 'SIMULATED_FILLED', "
                            "updated_at = ? WHERE intent_id = ?",
                            (
                                datetime.now(UTC).isoformat(),
                                commit_reservation_intent_id,
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
                # Outbox for optional risk-store projection (not atomic across DBs).
                if payload.get("outbox"):
                    conn.execute(
                        "INSERT INTO shadow_outbox (kind, payload_json, created_at) "
                        "VALUES (?, ?, ?)",
                        (
                            payload["outbox"]["kind"],
                            json.dumps(payload["outbox"]["payload"], default=str),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                conn.commit()
                return cycle_id
            except Exception:
                conn.rollback()
                raise

    def list_transitions(
        self, intent_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if intent_id:
                rows = conn.execute(
                    "SELECT * FROM shadow_transitions WHERE intent_id = ? ORDER BY id DESC LIMIT ?",
                    (intent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM shadow_transitions ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def pending_intents(self) -> list[dict[str, Any]]:
        return self.list_pending_intents()

    def list_pending_intents(self) -> list[dict[str, Any]]:
        """Unresolved intents, oldest first (chronological resume order)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM shadow_intents WHERE state IN "
                "('PENDING_DATA', 'RESERVED', 'RISK_APPROVED', 'SIGNAL_RECORDED') "
                "ORDER BY created_at ASC, intent_id ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_intent(self, intent_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM shadow_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def recovery_status(self) -> dict[str, Any]:
        """Pure inspection — never mutates reservations or ledger."""
        active = self.list_active_reservations()
        pending = self.list_pending_intents()
        undelivered = self.list_outbox(undelivered_only=True, limit=1000)
        return {
            "recovery_required": len(active) > 0,
            "active_reservations": active,
            "pending_intent_count": len(pending),
            "pending_intents": pending,
            "outbox_backlog": len(undelivered),
        }

    def list_outbox(
        self, *, undelivered_only: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if undelivered_only:
                rows = conn.execute(
                    "SELECT * FROM shadow_outbox WHERE projected_at IS NULL "
                    "ORDER BY id ASC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM shadow_outbox ORDER BY id ASC LIMIT ?",
                    (limit,),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            payload = json.loads(r["payload_json"])
            out.append(
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "payload": payload,
                    "payload_json": r["payload_json"],
                    "created_at": r["created_at"],
                    "projected_at": r["projected_at"],
                    "attempt_count": r["attempt_count"] if "attempt_count" in r.keys() else 0,
                    "last_error": r["last_error"] if "last_error" in r.keys() else "",
                }
            )
        return out

    def mark_outbox_delivered(self, outbox_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE shadow_outbox SET projected_at = ?, last_error = '' WHERE id = ?",
                (datetime.now(UTC).isoformat(), outbox_id),
            )
            conn.commit()

    def mark_outbox_attempt(self, outbox_id: int, *, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE shadow_outbox SET attempt_count = attempt_count + 1, "
                "last_error = ? WHERE id = ?",
                (error[:500], outbox_id),
            )
            conn.commit()

    def upsert_intent(
        self,
        *,
        intent_id: str,
        cycle_key: str,
        state: str,
        strategy_id: str,
        feed: str,
        symbol: str,
        evidence: dict[str, Any],
        evidence_hash: str,
        signal_session: str | None = None,
        fill_session: str | None = None,
        target_weight: str | None = None,
        from_state: str | None = None,
        reason: str = "",
        price_as_of: str | None = None,
        source_price: str | None = None,
        risk_verdict: str | None = None,
        ledger_version: int | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO shadow_intents (
                        intent_id, cycle_key, state, strategy_id, signal_session, fill_session,
                        feed, symbol, target_weight, evidence_json, evidence_hash,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(intent_id) DO UPDATE SET
                        state = excluded.state,
                        evidence_json = excluded.evidence_json,
                        evidence_hash = excluded.evidence_hash,
                        fill_session = excluded.fill_session,
                        target_weight = excluded.target_weight,
                        updated_at = excluded.updated_at
                    """,
                    (
                        intent_id,
                        cycle_key,
                        state,
                        strategy_id,
                        signal_session,
                        fill_session,
                        feed,
                        symbol,
                        target_weight,
                        json.dumps(evidence, default=str),
                        evidence_hash,
                        now,
                        now,
                    ),
                )
                self._append_transition(
                    conn,
                    intent_id=intent_id,
                    from_state=from_state,
                    to_state=state,
                    evidence_hash=evidence_hash,
                    reason=reason or state,
                    dataset_feed=feed,
                    signal_session=signal_session,
                    source_price=source_price,
                    price_as_of=price_as_of,
                    risk_verdict=risk_verdict,
                    ledger_before=ledger_version,
                    ledger_after=ledger_version,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _update_ledger_occ(
        self,
        conn: sqlite3.Connection,
        expected_version: int,
        ledger_after: dict[str, Any],
    ) -> int:
        new_version = expected_version + 1
        cur = conn.execute(
            """
            UPDATE shadow_ledger SET
                version = ?,
                cash_usd = ?,
                reserved_cash_usd = ?,
                holdings_json = ?,
                cost_basis_json = ?,
                realized_pnl_usd = ?,
                total_costs_usd = ?,
                peak_equity_usd = ?,
                updated_at = ?
            WHERE id = 1 AND version = ?
            """,
            (
                new_version,
                str(ledger_after["cash_usd"]),
                str(ledger_after["reserved_cash_usd"]),
                json.dumps({k: str(v) for k, v in ledger_after["holdings"].items()}),
                json.dumps({k: str(v) for k, v in ledger_after["cost_basis"].items()}),
                str(ledger_after["realized_pnl_usd"]),
                str(ledger_after["total_costs_usd"]),
                str(ledger_after["peak_equity_usd"]),
                datetime.now(UTC).isoformat(),
                expected_version,
            ),
        )
        if cur.rowcount != 1:
            raise ConcurrentModificationError(
                f"OCC conflict: expected ledger version {expected_version}."
            )
        return new_version

    def _append_transition(
        self,
        conn: sqlite3.Connection,
        *,
        intent_id: str,
        from_state: str | None,
        to_state: str,
        evidence_hash: str,
        reason: str,
        dataset_feed: str | None = None,
        signal_session: str | None = None,
        observation_cutoff: str | None = None,
        source_price: str | None = None,
        price_as_of: str | None = None,
        risk_verdict: str | None = None,
        ledger_before: int | None = None,
        ledger_after: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO shadow_transitions (
                intent_id, from_state, to_state, recorded_at, evidence_hash,
                dataset_feed, signal_session, observation_cutoff, source_price,
                price_as_of, risk_verdict, ledger_version_before, ledger_version_after,
                reason, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent_id,
                from_state,
                to_state,
                datetime.now(UTC).isoformat(),
                evidence_hash,
                dataset_feed,
                signal_session,
                observation_cutoff,
                source_price,
                price_as_of,
                risk_verdict,
                ledger_before,
                ledger_after,
                reason,
                json.dumps(payload or {}, default=str),
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def _ensure_outbox_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(shadow_outbox)").fetchall()}
    if "attempt_count" not in cols:
        conn.execute(
            "ALTER TABLE shadow_outbox ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
        )
    if "last_error" not in cols:
        conn.execute("ALTER TABLE shadow_outbox ADD COLUMN last_error TEXT NOT NULL DEFAULT ''")


def _ledger_row(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM shadow_ledger WHERE id = 1").fetchone()
    if not isinstance(row, sqlite3.Row):
        raise ShadowStoreError("shadow_ledger row missing.")
    return row


def _validate_ledger(ledger: dict[str, Any]) -> None:
    cash = Decimal(str(ledger["cash_usd"]))
    reserved = Decimal(str(ledger["reserved_cash_usd"]))
    if cash < 0:
        raise ValueError("Cash cannot be negative.")
    if reserved < 0:
        raise ValueError("Reserved cash cannot be negative.")
    if reserved > cash:
        raise ValueError("Reserved cash cannot exceed cash.")
    for sym, qty in dict(ledger.get("holdings") or {}).items():
        q = Decimal(str(qty))
        if q < 0:
            raise ValueError(f"Short holdings forbidden for {sym}.")


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
