"""Local audit records for daily decisions, tool calls, and notices."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_decisions (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            signal_session TEXT NOT NULL,
            execution_session TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_tool_calls (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS portfolio_checkpoints (
            id INTEGER PRIMARY KEY,
            as_of TEXT NOT NULL,
            equity_usd TEXT NOT NULL,
            realized_pnl_usd TEXT NOT NULL,
            peak_equity_usd TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_notices (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL
        );
        """
    )
    return connection


def save_decision(
    path: str, *, created_at: str, signal_session: str, payload: dict[str, Any]
) -> int:
    with _connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO daily_decisions (
                created_at, signal_session, execution_session, payload_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                created_at,
                signal_session,
                payload.get("execution_session"),
                json.dumps(payload),
            ),
        )
        return int(cursor.lastrowid or 0)


def latest_decision(path: str) -> dict[str, Any] | None:
    try:
        with _connect(path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM daily_decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except sqlite3.DatabaseError:
        return None
    if row is None:
        return None
    loaded = json.loads(str(row["payload_json"]))
    return loaded if isinstance(loaded, dict) else None


def save_tool_call(
    path: str, *, created_at: str, tool_name: str, status: str, payload: dict[str, Any]
) -> None:
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO daily_tool_calls (created_at, tool_name, status, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (created_at, tool_name, status, json.dumps(payload)[:20000]),
        )


def list_tool_calls(path: str, limit: int = 20) -> list[dict[str, Any]]:
    try:
        with _connect(path) as connection:
            rows = connection.execute(
                """
                SELECT tool_name, status, payload_json FROM daily_tool_calls
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.DatabaseError:
        return []
    return [
        {
            "tool": row["tool_name"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]),
        }
        for row in rows
    ]


def enqueue_notice(path: str, *, created_at: str, subject: str, body: str) -> dict[str, Any]:
    with _connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO daily_notices (created_at, subject, body, status, attempts)
            VALUES (?, ?, ?, 'queued', 0)
            """,
            (created_at, subject, body),
        )
        return {"id": int(cursor.lastrowid or 0), "status": "queued", "sent": False}


def note_equity(path: str, *, as_of: str, equity: str, realized: str) -> str:
    """Persist the high-water mark. A later lower equity does not replace it."""
    from decimal import Decimal

    current = Decimal(equity)
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT peak_equity_usd FROM portfolio_checkpoints ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prior = Decimal("100") if row is None else Decimal(str(row["peak_equity_usd"]))
        peak = max(prior, current)
        connection.execute(
            """
            INSERT INTO portfolio_checkpoints
                (as_of, equity_usd, realized_pnl_usd, peak_equity_usd)
            VALUES (?, ?, ?, ?)
            """,
            (as_of, equity, realized, format(peak, "f")),
        )
    return format(peak, "f")


def notice_body(path: str, notice_id: int) -> tuple[str, str] | None:
    try:
        with _connect(path) as connection:
            row = connection.execute(
                "SELECT subject, body FROM daily_notices WHERE id = ?",
                (notice_id,),
            ).fetchone()
    except sqlite3.DatabaseError:
        return None
    if row is None:
        return None
    return str(row["subject"]), str(row["body"])


def notice_status(path: str) -> dict[str, Any]:
    try:
        with _connect(path) as connection:
            row = connection.execute(
                "SELECT status, attempts, subject FROM daily_notices ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except sqlite3.DatabaseError:
        return {"status": "unavailable", "sent": False}
    if row is None:
        return {"status": "none", "sent": False}
    return {
        "status": row["status"],
        "attempts": row["attempts"],
        "subject": row["subject"],
        "sent": row["status"] == "delivered",
    }


def mark_notice(path: str, notice_id: int, *, status: str) -> None:
    with _connect(path) as connection:
        connection.execute(
            """
            UPDATE daily_notices
            SET status = ?, attempts = attempts + 1
            WHERE id = ?
            """,
            (status, notice_id),
        )
