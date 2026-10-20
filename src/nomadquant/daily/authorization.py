"""Bounded daily-pilot authorization. It stays off until the exact phrase is used."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from nomadquant.config import PAPER_API_URL, Settings
from nomadquant.daily.registry import SPECS, UNIVERSE

AUTHORIZE_PHRASE = "AUTHORIZE_DAILY_PAPER_PILOT"
MAX_DAYS = 30


def _connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_authorization (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            status TEXT NOT NULL,
            enabled_at TEXT,
            expires_at TEXT,
            killed_at TEXT,
            policy_json TEXT NOT NULL
        )
        """
    )
    return connection


def authorization_status(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    try:
        with _connect(settings.daily_path) as connection:
            row = connection.execute("SELECT * FROM daily_authorization WHERE id = 1").fetchone()
    except sqlite3.DatabaseError:
        return {"enabled": False, "reason": "authorization_unreadable", "schedule_installed": False}
    if row is None:
        return _off("daily_pilot_not_authorized")
    if row["status"] == "killed":
        return _off("killed", killed_at=row["killed_at"])
    expires = datetime.fromisoformat(str(row["expires_at"]))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= clock:
        return _off("authorization_expired", expires_at=expires.isoformat())
    if row["status"] != "enabled":
        return _off("daily_pilot_not_authorized")
    policy = json.loads(str(row["policy_json"]))
    return {
        "enabled": True,
        "reason": None,
        "expires_at": expires.isoformat(),
        "killed_at": None,
        "policy": policy,
        "schedule_installed": False,
        "paper_only": True,
    }


def authorize_daily_pilot(
    settings: Settings, *, confirm: str, days: int, now: datetime | None = None
) -> dict[str, Any]:
    """Arm the daily pilot. This does not submit an order and is not called at startup."""
    clock = now or datetime.now(UTC)
    if confirm != AUTHORIZE_PHRASE:
        raise ValueError("Daily pilot stays off without the exact authorization phrase.")
    if days < 1 or days > MAX_DAYS:
        raise ValueError("Daily pilot authorization must expire within 30 calendar days.")
    if settings.alpaca_base_url != PAPER_API_URL or settings.allow_order_submission:
        raise ValueError("Daily pilot authorization refuses a live endpoint or the live flag.")
    current = authorization_status(settings, now=clock)
    if current.get("reason") == "killed":
        raise ValueError("The emergency stop is active. Authorization was not re-enabled.")
    expires = clock + timedelta(days=days)
    policy = {
        "paper_only": True,
        "endpoint": PAPER_API_URL,
        "capital_usd": "100",
        "strategy_ids": sorted(SPECS),
        "universe": sorted(UNIVERSE),
        "max_new_notional_usd": "25",
        "max_orders_per_session": 1,
        "strategy_loss_stop_usd": "20",
        "sessions": "nyse_regular_hours",
        "per_trade_email_approval": False,
        "post_trade_email": "after_action_when_smtp_is_configured",
        "kill_phrase": "DISABLE_ALPACA_PAPER_ORDERS",
    }
    with _connect(settings.daily_path) as connection:
        connection.execute(
            """
            INSERT INTO daily_authorization (
                id, status, enabled_at, expires_at, killed_at, policy_json
            ) VALUES (1, 'enabled', ?, ?, NULL, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                enabled_at = excluded.enabled_at,
                expires_at = excluded.expires_at,
                killed_at = NULL,
                policy_json = excluded.policy_json
            """,
            (clock.isoformat(), expires.isoformat(), json.dumps(policy)),
        )
    return {"enabled": True, "expires_at": expires.isoformat(), "orders_sent": 0}


def revoke_daily_pilot(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    with _connect(settings.daily_path) as connection:
        connection.execute(
            """
            INSERT INTO daily_authorization (
                id, status, enabled_at, expires_at, killed_at, policy_json
            ) VALUES (1, 'killed', NULL, NULL, ?, '{}')
            ON CONFLICT(id) DO UPDATE SET
                status = 'killed',
                killed_at = excluded.killed_at
            """,
            (clock.isoformat(),),
        )
    return {"enabled": False, "killed": True, "schedule_installed": False}


def _off(reason: str, **extra: object) -> dict[str, Any]:
    return {
        "enabled": False,
        "reason": reason,
        "schedule_installed": False,
        "paper_only": True,
        **extra,
    }
