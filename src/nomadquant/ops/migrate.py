"""Stamp a schema version without discarding existing rows."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from nomadquant.ops import SCHEMA_VERSION

META_SQL = """
CREATE TABLE IF NOT EXISTS nomadquant_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""


def stamp_schema(path: Path) -> str:
    """Record schema version 1. Existing tables and rows stay in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(META_SQL)
        row = connection.execute(
            "SELECT value FROM nomadquant_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO nomadquant_meta (key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
        elif str(row[0]) != SCHEMA_VERSION:
            raise ValueError(f"Database {path.name} is schema {row[0]}, not {SCHEMA_VERSION}.")
        connection.commit()
    finally:
        connection.close()
    return SCHEMA_VERSION


def write_catalog(destination: Path, databases: dict[str, str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "databases": databases}, indent=2),
        encoding="utf-8",
    )
