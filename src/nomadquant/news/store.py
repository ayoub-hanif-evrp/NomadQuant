"""Stored headlines only. Article bodies are not copied."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    headline TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    symbols TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    model TEXT NOT NULL DEFAULT '',
    report_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS news_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    article_count INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS news_review_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    model TEXT NOT NULL DEFAULT '',
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
    error_safe TEXT NOT NULL DEFAULT ''
);
"""


class NewsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._readonly = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @classmethod
    def open_readonly(cls, path: str | Path) -> NewsStore | None:
        candidate = Path(path)
        if not candidate.is_file():
            return None
        store = cls.__new__(cls)
        store.path = candidate
        store._readonly = True
        return store

    def _connect(self) -> sqlite3.Connection:
        if getattr(self, "_readonly", False):
            conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def replace_articles(self, articles: list[dict[str, Any]], *, status: str, detail: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for article in articles:
                conn.execute(
                    """
                    INSERT INTO articles (
                        id, headline, source, url, published_at, updated_at,
                        retrieved_at, symbols, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        headline = excluded.headline,
                        updated_at = excluded.updated_at,
                        retrieved_at = excluded.retrieved_at,
                        symbols = excluded.symbols,
                        content_hash = excluded.content_hash
                    """,
                    (
                        article["id"],
                        article["headline"],
                        article["source"],
                        article["url"],
                        article["published_at"],
                        article["updated_at"],
                        now,
                        article["symbols"],
                        article["content_hash"],
                    ),
                )
            conn.execute(
                "INSERT INTO news_meta (key, value) VALUES ('status', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (json.dumps({"status": status, "detail": detail, "at": now}),),
            )
            conn.commit()

    def record_status(self, status: str, detail: str) -> None:
        payload = json.dumps(
            {"status": status, "detail": detail, "at": datetime.now(UTC).isoformat()}
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO news_meta (key, value) VALUES ('status', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (payload,),
            )

    def start_fetch(self, source: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO news_fetches (started_at, status, source) VALUES (?, 'running', ?)",
                (datetime.now(UTC).isoformat(), source),
            )
            return int(cursor.lastrowid or 0)

    def finish_fetch(
        self, fetch_id: int, *, status: str, count: int, duration_ms: int, detail: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE news_fetches
                SET finished_at = ?, status = ?, article_count = ?, duration_ms = ?, detail = ?
                WHERE id = ?
                """,
                (datetime.now(UTC).isoformat(), status, count, duration_ms, detail, fetch_id),
            )

    def fetches(self, limit: int = 10) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM news_fetches ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(row) for row in rows]

    def articles(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM articles ORDER BY published_at DESC LIMIT 30"
            ).fetchall()
        return [dict(row) for row in rows]

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM news_meta WHERE key = 'status'").fetchone()
        if row is None:
            return {"status": "not_loaded", "detail": "News has not been requested."}
        loaded = json.loads(row["value"])
        return loaded if isinstance(loaded, dict) else {"status": "not_loaded", "detail": ""}

    def article(self, article_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return None if row is None else dict(row)

    def add_review(self, article_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO news_reviews (article_id, status, created_at)
                VALUES (?, 'running', ?)
                """,
                (article_id, datetime.now(UTC).isoformat()),
            )
            return int(cursor.lastrowid or 0)

    def finish_review(
        self,
        review_id: int,
        *,
        status: str,
        model: str,
        report: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE news_reviews
                SET status = ?, finished_at = ?, model = ?, report_json = ?
                WHERE id = ?
                """,
                (status, datetime.now(UTC).isoformat(), model, json.dumps(report), review_id),
            )

    def start_stage(self, review_id: int, name: str, *, model: str, payload: dict[str, Any]) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO news_review_stages (
                    review_id, name, status, started_at, model, input_json
                ) VALUES (?, ?, 'running', ?, ?, ?)
                """,
                (
                    review_id,
                    name,
                    datetime.now(UTC).isoformat(),
                    model,
                    json.dumps(payload),
                ),
            )
            return int(cursor.lastrowid or 0)

    def finish_stage(
        self,
        stage_id: int,
        *,
        status: str,
        output: dict[str, Any],
        error_safe: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE news_review_stages
                SET status = ?, finished_at = ?, output_json = ?, error_safe = ?
                WHERE id = ?
                """,
                (
                    status,
                    datetime.now(UTC).isoformat(),
                    json.dumps(output),
                    error_safe[:500],
                    stage_id,
                ),
            )

    def stages(self, review_id: int) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM news_review_stages WHERE review_id = ? ORDER BY id",
                    (review_id,),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        result: list[dict[str, Any]] = []
        for row in rows:
            body = dict(row)
            body["input"] = json.loads(body.pop("input_json") or "{}")
            body["output"] = json.loads(body.pop("output_json") or "{}")
            result.append(body)
        return result

    def review(self, review_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM news_reviews WHERE id = ?", (review_id,)).fetchone()
        if row is None:
            return None
        body = dict(row)
        body["report"] = json.loads(body.pop("report_json") or "{}")
        body["stages"] = self.stages(review_id)
        return body


def headline_hash(headline: str, published_at: str) -> str:
    return hashlib.sha256(f"{published_at}|{headline}".encode()).hexdigest()
