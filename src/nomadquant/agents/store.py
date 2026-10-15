"""SQLite history of agent runs. Separate from market, research and audit data.

Finished runs, finished stages and artifacts are never overwritten. A retry
either creates a new run or resumes an unfinished run whose fingerprint matches.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nomadquant.agents.constants import PROMPT_VERSION, RUN_LABEL, TOOL_SCHEMA_VERSION

RESULT_PREVIEW_LIMIT = 16000

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    research_run_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    tool_schema_version TEXT NOT NULL,
    as_of TEXT NOT NULL,
    label TEXT NOT NULL,
    verdict TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    config_json TEXT NOT NULL DEFAULT '{}',
    resumed_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '',
    error_message_safe TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS agent_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    prompt_sha256 TEXT NOT NULL DEFAULT '',
    output_json TEXT NOT NULL DEFAULT '{}',
    model_calls INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    error_code TEXT NOT NULL DEFAULT '',
    error_message_safe TEXT NOT NULL DEFAULT '',
    UNIQUE (run_id, name, attempt),
    FOREIGN KEY (run_id) REFERENCES agent_runs(id)
);
CREATE TABLE IF NOT EXISTS agent_tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    stage_id INTEGER,
    stage_name TEXT NOT NULL,
    seq INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '',
    result_sha256 TEXT NOT NULL DEFAULT '',
    result_truncated INTEGER NOT NULL DEFAULT 0,
    error_message_safe TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, seq),
    FOREIGN KEY (run_id) REFERENCES agent_runs(id)
);
CREATE TABLE IF NOT EXISTS agent_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    stage_id INTEGER,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, kind, name),
    FOREIGN KEY (run_id) REFERENCES agent_runs(id)
);
CREATE INDEX IF NOT EXISTS agent_runs_research ON agent_runs (research_run_id);
CREATE INDEX IF NOT EXISTS agent_tool_calls_run ON agent_tool_calls (run_id, seq);
"""


class AgentStoreError(ValueError):
    """A write would overwrite finished history or violate resume rules."""


class AgentStore:
    def __init__(self, path: str | Path = "data/agents.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    # -- runs ---------------------------------------------------------------

    def create_run(
        self,
        *,
        research_run_id: int,
        model: str,
        fingerprint: str,
        as_of: str = "",
        config: dict[str, Any] | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        """Create a run, or with resume=True reuse a matching unfinished run."""
        if resume:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM agent_runs
                    WHERE fingerprint = ? AND status IN ('running', 'failed')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (fingerprint,),
                ).fetchone()
            if row is not None:
                return self.resume_run(int(row["id"]), fingerprint)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO agent_runs (
                    created_at, status, research_run_id, model, fingerprint,
                    prompt_version, tool_schema_version, as_of, label, config_json
                ) VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now(),
                    research_run_id,
                    model,
                    fingerprint,
                    PROMPT_VERSION,
                    TOOL_SCHEMA_VERSION,
                    as_of,
                    RUN_LABEL,
                    json.dumps(config or {}, sort_keys=True, default=str),
                ),
            )
            run_id = int(cursor.lastrowid or 0)
        created = self.get_run(run_id)
        assert created is not None
        return created

    def resume_run(self, run_id: int, fingerprint: str) -> dict[str, Any]:
        """Reopen an unfinished run. Refuses finished runs and fingerprint mismatches."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise AgentStoreError(f"Agent run {run_id} was not found.")
            if row["status"] == "succeeded":
                raise AgentStoreError(
                    f"Agent run {run_id} is finished and immutable. Start a new run instead."
                )
            if row["fingerprint"] != fingerprint:
                raise AgentStoreError(
                    f"Agent run {run_id} fingerprint does not match the current inputs. "
                    "Start a new run instead."
                )
            connection.execute(
                """
                UPDATE agent_runs
                SET status = 'running', finished_at = NULL, error_code = '',
                    error_message_safe = '', resumed_count = resumed_count + 1
                WHERE id = ?
                """,
                (run_id,),
            )
        reopened = self.get_run(run_id)
        assert reopened is not None
        return reopened

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        verdict: str = "",
        summary: str = "",
        result: dict[str, Any] | None = None,
        error_code: str = "",
        error_message_safe: str = "",
    ) -> None:
        if status not in {"succeeded", "failed"}:
            raise AgentStoreError(f"Unsupported final status {status!r}.")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_runs
                SET finished_at = ?, status = ?, verdict = ?, summary = ?, result_json = ?,
                    error_code = ?, error_message_safe = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    _now(),
                    status,
                    verdict,
                    summary,
                    json.dumps(result or {}, sort_keys=True, default=str),
                    error_code,
                    error_message_safe[:500],
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentStoreError(f"Agent run {run_id} is not running and cannot be finished.")

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        return None if row is None else _run(row)

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_runs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [_run(row) for row in rows]

    def count_runs(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM agent_runs").fetchone()
        return int(row["n"])

    # -- stages -------------------------------------------------------------

    def start_stage(self, run_id: int, name: str, role: str, *, prompt_sha256: str = "") -> int:
        """Open a new stage attempt. A succeeded stage is never reopened."""
        with self._connect() as connection:
            done = connection.execute(
                "SELECT id FROM agent_stages "
                "WHERE run_id = ? AND name = ? AND status = 'succeeded'",
                (run_id, name),
            ).fetchone()
            if done is not None:
                raise AgentStoreError(f"Stage {name!r} already succeeded for run {run_id}.")
            open_row = connection.execute(
                "SELECT id FROM agent_stages WHERE run_id = ? AND name = ? AND status = 'running'",
                (run_id, name),
            ).fetchone()
            if open_row is not None:
                # A crashed attempt: close it as interrupted, then start a fresh attempt.
                connection.execute(
                    """
                    UPDATE agent_stages
                    SET status = 'failed', finished_at = ?, error_code = 'interrupted'
                    WHERE id = ?
                    """,
                    (_now(), open_row["id"]),
                )
            attempt = int(
                connection.execute(
                    "SELECT COALESCE(MAX(attempt), 0) + 1 AS n FROM agent_stages "
                    "WHERE run_id = ? AND name = ?",
                    (run_id, name),
                ).fetchone()["n"]
            )
            cursor = connection.execute(
                """
                INSERT INTO agent_stages (
                    run_id, name, role, attempt, status, started_at, prompt_sha256
                ) VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
                (run_id, name, role, attempt, _now(), prompt_sha256),
            )
            return int(cursor.lastrowid or 0)

    def finish_stage(
        self,
        stage_id: int,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        model_calls: int = 0,
        latency_ms: int = 0,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        error_code: str = "",
        error_message_safe: str = "",
    ) -> None:
        if status not in {"succeeded", "failed"}:
            raise AgentStoreError(f"Unsupported stage status {status!r}.")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_stages
                SET status = ?, finished_at = ?, output_json = ?, model_calls = ?,
                    latency_ms = ?, prompt_tokens = ?, completion_tokens = ?,
                    error_code = ?, error_message_safe = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    status,
                    _now(),
                    json.dumps(output or {}, sort_keys=True, default=str),
                    model_calls,
                    latency_ms,
                    prompt_tokens,
                    completion_tokens,
                    error_code,
                    error_message_safe[:500],
                    stage_id,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentStoreError(f"Stage {stage_id} is not running and cannot be finished.")

    def stage_output(self, run_id: int, name: str) -> dict[str, Any] | None:
        """Output of a succeeded stage, or None."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT output_json FROM agent_stages "
                "WHERE run_id = ? AND name = ? AND status = 'succeeded'",
                (run_id, name),
            ).fetchone()
        if row is None:
            return None
        loaded: dict[str, Any] = json.loads(row["output_json"])
        return loaded

    def list_stages(self, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_stages WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "role": row["role"],
                "attempt": row["attempt"],
                "status": row["status"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "prompt_sha256": row["prompt_sha256"],
                "output": json.loads(row["output_json"]),
                "model_calls": row["model_calls"],
                "latency_ms": row["latency_ms"],
                "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "error_code": row["error_code"],
                "error_message_safe": row["error_message_safe"],
            }
            for row in rows
        ]

    # -- tool calls ---------------------------------------------------------

    def record_tool_call(
        self,
        run_id: int,
        *,
        stage_id: int | None,
        stage_name: str,
        seq: int,
        tool_name: str,
        arguments: dict[str, Any],
        status: str,
        result: dict[str, Any] | None = None,
        error: str = "",
        latency_ms: int = 0,
    ) -> int:
        if status not in {"ok", "rejected", "error"}:
            raise AgentStoreError(f"Unsupported tool call status {status!r}.")
        full = "" if result is None else json.dumps(result, sort_keys=True, default=str)
        preview = full[:RESULT_PREVIEW_LIMIT]
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO agent_tool_calls (
                    run_id, stage_id, stage_name, seq, tool_name, arguments_json, status,
                    result_json, result_sha256, result_truncated, error_message_safe,
                    latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    stage_id,
                    stage_name,
                    seq,
                    tool_name[:200],
                    json.dumps(arguments, sort_keys=True, default=str)[:RESULT_PREVIEW_LIMIT],
                    status,
                    preview,
                    hashlib.sha256(full.encode("utf-8")).hexdigest() if full else "",
                    int(len(full) > len(preview)),
                    error[:500],
                    latency_ms,
                    _now(),
                ),
            )
            return int(cursor.lastrowid or 0)

    def count_tool_calls(self, run_id: int) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) AS n FROM agent_tool_calls WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["n"])

    def list_tool_calls(self, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_tool_calls WHERE run_id = ? ORDER BY seq", (run_id,)
            ).fetchall()
        return [
            {
                "id": row["id"],
                "stage_id": row["stage_id"],
                "stage_name": row["stage_name"],
                "seq": row["seq"],
                "tool_name": row["tool_name"],
                "arguments": _loads(row["arguments_json"]),
                "status": row["status"],
                "result": _loads(row["result_json"]) if not row["result_truncated"] else None,
                "result_preview": row["result_json"] if row["result_truncated"] else "",
                "result_sha256": row["result_sha256"],
                "result_truncated": bool(row["result_truncated"]),
                "error_message_safe": row["error_message_safe"],
                "latency_ms": row["latency_ms"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # -- artifacts ----------------------------------------------------------

    def save_artifact(
        self,
        run_id: int,
        *,
        kind: str,
        name: str,
        content: str | dict[str, Any] | list[Any],
        stage_id: int | None = None,
        media_type: str = "application/json",
    ) -> str:
        """Store an immutable artifact. Re-saving identical content is a no-op."""
        text = (
            content
            if isinstance(content, str)
            else json.dumps(content, sort_keys=True, default=str)
        )
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT sha256 FROM agent_artifacts WHERE run_id = ? AND kind = ? AND name = ?",
                (run_id, kind, name),
            ).fetchone()
            if existing is not None:
                if existing["sha256"] == digest:
                    return digest
                raise AgentStoreError(
                    f"Artifact {kind}/{name} already exists for run {run_id} with other content."
                )
            connection.execute(
                """
                INSERT INTO agent_artifacts (
                    run_id, stage_id, kind, name, media_type, sha256, byte_size, content,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    stage_id,
                    kind,
                    name,
                    media_type,
                    digest,
                    len(text.encode("utf-8")),
                    text,
                    _now(),
                ),
            )
        return digest

    def list_artifacts(self, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_artifacts WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        return [
            {
                "id": row["id"],
                "stage_id": row["stage_id"],
                "kind": row["kind"],
                "name": row["name"],
                "media_type": row["media_type"],
                "sha256": row["sha256"],
                "byte_size": row["byte_size"],
                "content": _loads(row["content"])
                if row["media_type"] == "application/json"
                else row["content"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # -- views --------------------------------------------------------------

    def get_run_detail(self, run_id: int) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        return {
            **run,
            "stages": self.list_stages(run_id),
            "tool_calls": self.list_tool_calls(run_id),
            "artifacts": self.list_artifacts(run_id),
        }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _loads(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
        "status": row["status"],
        "research_run_id": row["research_run_id"],
        "model": row["model"],
        "fingerprint": row["fingerprint"],
        "prompt_version": row["prompt_version"],
        "tool_schema_version": row["tool_schema_version"],
        "as_of": row["as_of"],
        "label": row["label"],
        "verdict": row["verdict"],
        "summary": row["summary"],
        "result": json.loads(row["result_json"]),
        "config": json.loads(row["config_json"]),
        "resumed_count": row["resumed_count"],
        "error_code": row["error_code"],
        "error_message_safe": row["error_message_safe"],
        "is_trading_decision": False,
        "is_broker_execution": False,
    }
