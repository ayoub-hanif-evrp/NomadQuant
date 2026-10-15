"""Local audit log for operational events, runs, and decision traces.

This store is separate from market bars. It never records credentials.
JSON payloads are never truncated into invalid JSON. Oversized evidence is
stored as content-addressed artifacts with a safe reference in the row.
"""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nomadquant.logging import redact_text

COMPONENTS = frozenset(
    {
        "system",
        "broker",
        "market_data",
        "research",
        "backtest",
        "strategy",
        "risk",
        "agent",
        "execution",
        "ui",
    }
)
LEVELS = frozenset({"info", "warning", "error"})
STATUSES = frozenset({"started", "succeeded", "failed", "warning", "skipped", "empty"})
ACTIONS = frozenset({"buy", "sell", "hold", "reject", "no_trade"})
TEXT_LIMIT = 2000
INLINE_PAYLOAD_LIMIT = 8192
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "api_secret",
        "secret",
        "password",
        "token",
        "authorization",
        "bearer",
        "alpaca_api_key",
        "alpaca_api_secret",
        "access_token",
        "refresh_token",
        "private_key",
        ".env",
    }
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_level TEXT NOT NULL,
    component TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    run_id INTEGER,
    payload_json TEXT NOT NULL,
    error_code TEXT NOT NULL,
    error_message_safe TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    run_type TEXT NOT NULL,
    component TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    error_code TEXT NOT NULL,
    error_message_safe TEXT NOT NULL,
    external_key TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS decision_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source_type TEXT NOT NULL,
    symbols TEXT NOT NULL,
    decision_action TEXT NOT NULL,
    proposed_notional TEXT,
    decision_status TEXT NOT NULL,
    rationale_summary TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    warnings TEXT NOT NULL,
    market_data_snapshot TEXT NOT NULL,
    research_note_ids TEXT NOT NULL,
    backtest_id TEXT,
    risk_decision_id TEXT,
    broker_event_id TEXT,
    model_provider TEXT,
    confidence TEXT,
    explanation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_artifacts (
    sha256 TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_created ON audit_events (created_at);
CREATE INDEX IF NOT EXISTS audit_events_component ON audit_events (component);
"""


class AuditLog:
    def __init__(self, path: str | Path, secrets: list[str] | None = None) -> None:
        self.path = Path(path)
        self._secrets = [secret for secret in (secrets or []) if secret]
        self.ensure()

    def ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def record_event(
        self,
        *,
        event_type: str,
        event_level: str,
        component: str,
        status: str,
        title: str,
        summary: str,
        correlation_id: str = "",
        run_id: int | None = None,
        payload: dict[str, Any] | None = None,
        error_code: str = "",
        error_message_safe: str = "",
    ) -> int:
        _require(event_level, LEVELS, "event level")
        _require(component, COMPONENTS, "component")
        _require(status, STATUSES, "status")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO audit_events (
                    created_at, event_type, event_level, component, status, title,
                    summary, correlation_id, run_id, payload_json, error_code,
                    error_message_safe
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now(),
                    self._clean(event_type),
                    event_level,
                    component,
                    status,
                    self._clean(title),
                    self._clean(summary),
                    self._clean(correlation_id),
                    run_id,
                    self._store_payload(payload or {}),
                    self._clean(error_code),
                    self._clean(error_message_safe),
                ),
            )
            return int(cursor.lastrowid or 0)

    def start_run(
        self,
        *,
        run_type: str,
        component: str,
        title: str,
        summary: str,
        correlation_id: str = "",
        payload: dict[str, Any] | None = None,
        external_key: str | None = None,
    ) -> int:
        _require(component, COMPONENTS, "component")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO runs (
                    created_at, finished_at, run_type, component, status, title,
                    summary, correlation_id, payload_json, error_code,
                    error_message_safe, external_key
                ) VALUES (?, NULL, ?, ?, 'started', ?, ?, ?, ?, '', '', ?)
                """,
                (
                    _now(),
                    self._clean(run_type),
                    component,
                    self._clean(title),
                    self._clean(summary),
                    self._clean(correlation_id),
                    self._store_payload(payload or {}),
                    external_key,
                ),
            )
            return int(cursor.lastrowid or 0)

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        error_code: str = "",
        error_message_safe: str = "",
    ) -> None:
        _require(status, STATUSES, "status")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown run id {run_id}.")
            existing = self._resolve_payload_text(connection, str(row["payload_json"]))
            merged = {**existing, **(payload or {})}
            if "config" in existing and "config" not in (payload or {}):
                merged["config"] = existing["config"]
            for key in ("dataset", "hypothesis_id", "experiment_id", "engine_version"):
                if key in existing and key not in (payload or {}):
                    merged[key] = existing[key]
            connection.execute(
                """
                UPDATE runs
                SET finished_at = ?, status = ?, summary = ?, payload_json = ?,
                    error_code = ?, error_message_safe = ?
                WHERE id = ?
                """,
                (
                    _now(),
                    status,
                    self._clean(summary),
                    self._encode_payload(connection, merged),
                    self._clean(error_code),
                    self._clean(error_message_safe),
                    run_id,
                ),
            )

    def get_artifact(self, sha256: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM audit_artifacts WHERE sha256 = ?", (sha256,)
            ).fetchone()
        if row is None:
            return None
        return {
            "sha256": row["sha256"],
            "created_at": row["created_at"],
            "media_type": row["media_type"],
            "byte_size": row["byte_size"],
            "content": row["content"],
        }

    def record_decision(
        self,
        *,
        source_type: str,
        symbols: list[str],
        decision_action: str,
        decision_status: str,
        rationale_summary: str,
        evidence_summary: str,
        warnings: str = "",
        market_data_snapshot: str = "",
        research_note_ids: str = "",
        proposed_notional: str | None = None,
        backtest_id: str | None = None,
        risk_decision_id: str | None = None,
        broker_event_id: str | None = None,
        model_provider: str | None = None,
        confidence: str | None = None,
        explanation: dict[str, Any] | None = None,
    ) -> int:
        _require(decision_action, ACTIONS, "decision action")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO decision_traces (
                    created_at, source_type, symbols, decision_action, proposed_notional,
                    decision_status, rationale_summary, evidence_summary, warnings,
                    market_data_snapshot, research_note_ids, backtest_id, risk_decision_id,
                    broker_event_id, model_provider, confidence, explanation_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now(),
                    self._clean(source_type),
                    self._clean(",".join(symbols)),
                    decision_action,
                    None if proposed_notional is None else self._clean(proposed_notional),
                    self._clean(decision_status),
                    self._clean(rationale_summary),
                    self._clean(evidence_summary),
                    self._clean(warnings),
                    self._clean(market_data_snapshot),
                    self._clean(research_note_ids),
                    backtest_id,
                    risk_decision_id,
                    broker_event_id,
                    model_provider,
                    confidence,
                    self._store_payload(explanation or {}),
                ),
            )
            return int(cursor.lastrowid or 0)

    def list_events(
        self, filters: dict[str, str], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        return self._list("audit_events", filters, limit, offset, _event)

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM audit_events WHERE id = ?", (event_id,), _event)

    def list_runs(
        self, filters: dict[str, str], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        return self._list("runs", filters, limit, offset, _run)

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM runs WHERE id = ?", (run_id,), _run)

    def list_decisions(self, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        return self._list("decision_traces", {}, limit, offset, _decision)

    def get_decision(self, decision_id: int) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM decision_traces WHERE id = ?",
            (decision_id,),
            _decision,
        )

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            events = _count(connection, "audit_events")
            warnings = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM audit_events
                    WHERE event_level = 'warning' OR status = 'warning'
                    """
                ).fetchone()[0]
            )
            errors = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM audit_events
                    WHERE event_level = 'error' OR status = 'failed'
                    """
                ).fetchone()[0]
            )
            return {
                "events": events,
                "warnings": warnings,
                "errors": errors,
                "runs": _count(connection, "runs"),
                "decision_traces": _count(connection, "decision_traces"),
            }

    def recent_events(self, limit: int = 8) -> list[dict[str, Any]]:
        items, _total = self.list_events({}, limit, 0)
        return items

    def mirror_market_imports(self, market_path: str) -> None:
        path = Path(market_path)
        if not path.exists():
            return
        try:
            with sqlite3.connect(path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute("SELECT * FROM import_runs ORDER BY id").fetchall()
        except sqlite3.Error:
            return
        for row in rows:
            key = f"market-import-{row['id']}"
            status = _import_status(str(row["status"]))
            summary = (
                f"{row['symbols']} {row['feed']} {row['start_date']}..{row['end_date']}: "
                f"fetched {row['rows_fetched']}, inserted {row['rows_inserted']}, "
                f"unchanged {row['rows_unchanged']}, conflicts {row['rows_conflict']}."
            )
            payload = {
                "import_run_id": row["id"],
                "feed": row["feed"],
                "symbols": row["symbols"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "rows_fetched": row["rows_fetched"],
                "rows_inserted": row["rows_inserted"],
                "rows_unchanged": row["rows_unchanged"],
                "rows_conflict": row["rows_conflict"],
                "warnings": row["warnings"],
            }
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO runs (
                        created_at, finished_at, run_type, component, status, title,
                        summary, correlation_id, payload_json, error_code,
                        error_message_safe, external_key
                    ) VALUES (?, ?, 'market_data_sync', 'market_data', ?, ?, ?, ?, ?, ?, '', ?)
                    """,
                    (
                        row["started_at"],
                        row["finished_at"],
                        status,
                        "Market data sync",
                        self._clean(summary),
                        key,
                        self._store_payload(payload),
                        self._clean(str(row["error_code"])),
                        key,
                    ),
                )

    def _list(
        self,
        table: str,
        filters: dict[str, str],
        limit: int,
        offset: int,
        mapper: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = _where(filters)
        query = f"SELECT * FROM {table} {where} ORDER BY id DESC LIMIT ? OFFSET ?"
        count_query = f"SELECT COUNT(*) FROM {table} {where}"
        with self._connect() as connection:
            total = int(connection.execute(count_query, params).fetchone()[0])
            rows = connection.execute(query, [*params, limit, offset]).fetchall()
            items = [self._hydrate(connection, mapper(row)) for row in rows]
        return items, total

    def _one(self, query: str, params: tuple[object, ...], mapper: Any) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
            if row is None:
                return None
            mapped: dict[str, Any] = self._hydrate(connection, mapper(row))
        return mapped

    def _hydrate(self, connection: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any]:
        if "payload" in item and isinstance(item["payload"], dict):
            digest = item["payload"].get("_artifact_sha256")
            if isinstance(digest, str):
                item["payload"] = self._resolve_payload_text(
                    connection, json.dumps({"_artifact_sha256": digest})
                )
        if "explanation" in item and isinstance(item["explanation"], dict):
            digest = item["explanation"].get("_artifact_sha256")
            if isinstance(digest, str):
                item["explanation"] = self._resolve_payload_text(
                    connection, json.dumps({"_artifact_sha256": digest})
                )
        return item

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _clean(self, value: str) -> str:
        return redact_text(value, self._secrets)[:TEXT_LIMIT]

    def _store_payload(self, payload: dict[str, Any]) -> str:
        with self._connect() as connection:
            return self._encode_payload(connection, payload)

    def _encode_payload(self, connection: sqlite3.Connection, payload: dict[str, Any]) -> str:
        cleaned = _sanitize(payload, self._secrets)
        encoded = json.dumps(cleaned, ensure_ascii=True, default=str, separators=(",", ":"))
        encoded = redact_text(encoded, self._secrets)
        if len(encoded.encode("utf-8")) <= INLINE_PAYLOAD_LIMIT:
            return encoded
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        connection.execute(
            """
            INSERT OR IGNORE INTO audit_artifacts
            (sha256, created_at, media_type, byte_size, content)
            VALUES (?, ?, 'application/json', ?, ?)
            """,
            (digest, _now(), len(encoded.encode("utf-8")), encoded),
        )
        ref = {
            "_artifact_sha256": digest,
            "_artifact_bytes": len(encoded.encode("utf-8")),
        }
        return json.dumps(ref, ensure_ascii=True, separators=(",", ":"))

    def _resolve_payload_text(self, connection: sqlite3.Connection, raw: str) -> dict[str, Any]:
        parsed = _loads(raw)
        digest = parsed.get("_artifact_sha256")
        if not isinstance(digest, str):
            return parsed
        row = connection.execute(
            "SELECT content FROM audit_artifacts WHERE sha256 = ?", (digest,)
        ).fetchone()
        if row is None:
            return {
                "_artifact_sha256": digest,
                "_artifact_missing": True,
                "warning": "Referenced audit artifact is missing.",
            }
        return _loads(str(row["content"]))


def _require(value: str, allowed: frozenset[str], label: str) -> None:
    if value not in allowed:
        raise ValueError(f"Unsupported {label}.")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _where(filters: dict[str, str]) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    columns = {
        "component": "component",
        "status": "status",
        "event_level": "event_level",
        "event_type": "event_type",
        "run_type": "run_type",
    }
    for key, column in columns.items():
        value = filters.get(key)
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if filters.get("start"):
        clauses.append("created_at >= ?")
        params.append(filters["start"])
    if filters.get("end"):
        clauses.append("created_at <= ?")
        params.append(filters["end"])
    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _loads(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _sanitize(value: object, secrets: list[str]) -> object:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in SENSITIVE_KEYS or any(
                token in lowered for token in ("secret", "password", "token", "api_key")
            ):
                cleaned[str(key)] = "[REDACTED]"
                continue
            cleaned[str(key)] = _sanitize(item, secrets)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


def _blank(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "event_type": row["event_type"],
        "event_level": row["event_level"],
        "component": row["component"],
        "status": row["status"],
        "title": row["title"],
        "summary": row["summary"],
        "correlation_id": row["correlation_id"],
        "run_id": row["run_id"],
        "payload": _loads(row["payload_json"]),
        "error_code": _blank(row["error_code"]),
        "error_message_safe": _blank(row["error_message_safe"]),
    }


def _run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
        "run_type": row["run_type"],
        "component": row["component"],
        "status": row["status"],
        "title": row["title"],
        "summary": row["summary"],
        "correlation_id": row["correlation_id"],
        "payload": _loads(row["payload_json"]),
        "error_code": _blank(row["error_code"]),
        "error_message_safe": _blank(row["error_message_safe"]),
    }


def _decision(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "source_type": row["source_type"],
        "symbols": [part for part in str(row["symbols"]).split(",") if part],
        "decision_action": row["decision_action"],
        "proposed_notional": row["proposed_notional"],
        "decision_status": row["decision_status"],
        "rationale_summary": row["rationale_summary"],
        "evidence_summary": row["evidence_summary"],
        "warnings": row["warnings"],
        "market_data_snapshot": row["market_data_snapshot"],
        "research_note_ids": row["research_note_ids"],
        "backtest_id": row["backtest_id"],
        "risk_decision_id": row["risk_decision_id"],
        "broker_event_id": row["broker_event_id"],
        "model_provider": row["model_provider"],
        "confidence": row["confidence"],
        "explanation": _loads(row["explanation_json"]),
    }


def _import_status(value: str) -> str:
    if value == "success":
        return "succeeded"
    if value == "failed":
        return "failed"
    if value == "incomplete":
        return "warning"
    return "warning"
