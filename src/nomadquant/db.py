"""SQLite operational events. This is not a market-data or research store."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from nomadquant.audit import AuditLog


def init_db(database_path: str) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    AuditLog(path).ensure()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO system_events (created_at, event_type, message)
            VALUES (?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                "startup",
                "NomadQuant API started in paper mode with order submission disabled",
            ),
        )


def database_ok(database_path: str) -> bool:
    path = Path(database_path)
    if not path.exists():
        return False
    try:
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'system_events'"
            ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
