"""One-time internal shadow-apply approval. Not a broker order authorization."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nomadquant.risk.policy import RiskPolicy
from nomadquant.shadow.cycle import FEED, LOOKBACK, SKIP, STRATEGY_ID, SYMBOL
from nomadquant.shadow.store import ShadowStore

APPROVAL_KEY = "shadow_apply_approval"
SCHEDULE_KEY = "scheduled_shadow_cycles"
AUDIT_KEY = "shadow_authorization_audit"
APPROVABLE_STATES = frozenset({"READY_TO_START", "AWAITING_USER_APPROVAL"})
ARMABLE_STATES = frozenset(
    {
        "READY_TO_START",
        "WAITING_FOR_SESSION",
        "WAITING_FOR_DATA",
        "AWAITING_USER_APPROVAL",
    }
)
APPROVAL_TTL = timedelta(minutes=30)
SCHEDULE_MAX = timedelta(days=31)
SCOPE = "internal_shadow_simulation_only"
OPERATION = "forward_shadow_apply"
SCHEDULE_OPT_IN = "ENABLE_INTERNAL_SHADOW_SCHEDULE"
SCHEDULE_OPT_OUT = "DISABLE_INTERNAL_SHADOW_SCHEDULE"
FINGERPRINT_VERSION = "v2"


def state_can_be_approved(state: str) -> bool:
    return state in APPROVABLE_STATES


def state_can_be_armed(state: str) -> bool:
    """True when the user may persist the pilot clock without a fill grant."""
    return state in ARMABLE_STATES


def issue_shadow_approval(
    store: ShadowStore, binding: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Store one pending approval. A second pending approval is rejected."""
    if now.tzinfo is None:
        raise ValueError("Approval clock must be timezone-aware.")
    existing = _load(store)
    if existing is not None and existing.get("status") == "pending":
        expires = datetime.fromisoformat(str(existing["expires_at"]))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires > now:
            raise ValueError("A pending shadow approval already exists.")
    record = {
        **binding,
        "grant_id": secrets.token_hex(8),
        "status": "pending",
        "scope": SCOPE,
        "operation": OPERATION,
        "broker_orders": False,
        "issued_at": now.isoformat(),
        "expires_at": (now + APPROVAL_TTL).isoformat(),
        "consumed_at": None,
    }
    _write_record(store, APPROVAL_KEY, record, action="approval_issued", now=now)
    return record


def enable_scheduled_shadow_cycles(
    store: ShadowStore,
    *,
    now: datetime,
    confirm: str,
    expires_at: datetime,
    policy: RiskPolicy | None = None,
) -> dict[str, Any]:
    """Explicit bounded schedule. Installation and pilot confirm must not call this."""
    if now.tzinfo is None or expires_at.tzinfo is None:
        raise ValueError("Schedule clock must be timezone-aware.")
    if confirm != SCHEDULE_OPT_IN:
        raise ValueError("Schedule opt-in confirmation does not match.")
    if expires_at <= now or expires_at - now > SCHEDULE_MAX:
        raise ValueError("Schedule authorization must expire within 31 days.")
    chosen = policy or RiskPolicy()
    record = {
        "id": secrets.token_hex(8),
        "status": "enabled",
        "scope": SCOPE,
        "operation": OPERATION,
        "broker_orders": False,
        "strategy_id": STRATEGY_ID,
        "policy_hash": chosen.policy_hash(),
        "feed": FEED,
        "enabled_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "disabled_at": None,
    }
    _write_record(store, SCHEDULE_KEY, record, action="schedule_enabled", now=now)
    return record


def disable_scheduled_shadow_cycles(
    store: ShadowStore, *, now: datetime, confirm: str
) -> dict[str, Any]:
    """Turn scheduled internal shadow cycles off. Does not authorize a broker order."""
    if now.tzinfo is None:
        raise ValueError("Schedule clock must be timezone-aware.")
    if confirm != SCHEDULE_OPT_OUT:
        raise ValueError("Schedule opt-out confirmation does not match.")
    current = _load_json(store, SCHEDULE_KEY) or {}
    record = {
        **current,
        "status": "disabled",
        "scope": SCOPE,
        "broker_orders": False,
        "disabled_at": now.isoformat(),
    }
    _write_record(store, SCHEDULE_KEY, record, action="schedule_disabled", now=now)
    return record


def consume_shadow_approval(conn: Any, binding: dict[str, Any], *, now: datetime) -> None:
    """Mark the pending approval consumed inside the caller's transaction."""
    row = conn.execute(
        "SELECT value FROM shadow_meta WHERE key = ?",
        (APPROVAL_KEY,),
    ).fetchone()
    if row is None:
        raise ValueError("No shadow approval is stored.")
    record = json.loads(row["value"] if hasattr(row, "keys") else row[0])
    _require_match(record, binding, now)
    record["status"] = "consumed"
    record["consumed_at"] = now.isoformat()
    record["broker_orders"] = False
    conn.execute(
        "INSERT OR REPLACE INTO shadow_meta (key, value) VALUES (?, ?)",
        (APPROVAL_KEY, json.dumps(record, sort_keys=True)),
    )
    _append_audit_conn(
        conn,
        {
            "at": now.isoformat(),
            "action": "approval_consumed",
            "grant_id": record.get("grant_id"),
            "scope": SCOPE,
            "broker_orders": False,
            "reason": "consumed_with_operation",
        },
    )


def approval_decision(
    store: ShadowStore, binding: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Decide whether a new forward apply may proceed. Does not consume."""
    schedule = _schedule_allows(store, binding, now)
    if schedule is not None:
        return {
            "allowed": True,
            "consume": False,
            "reason": "scheduled_policy",
            "schedule_id": schedule["id"],
        }
    record = _load(store)
    if record is None:
        return {"allowed": False, "consume": False, "reason": "missing_shadow_approval"}
    try:
        _require_match(record, binding, now)
    except ValueError as exc:
        return {"allowed": False, "consume": False, "reason": str(exc)}
    return {
        "allowed": True,
        "consume": True,
        "reason": "one_time_approval",
        "binding": binding,
        "grant_id": record.get("grant_id"),
    }


def market_fingerprint(market_path: Path) -> str:
    """Versioned digest of the SPY SIP observations the strategy can use.

    A price change inside that window changes the digest even when the session
    count and the latest date stay the same. Empty coverage is explicit.
    """
    from nomadquant.marketdata.store import MarketStore

    if not market_path.is_file():
        return f"{FINGERPRINT_VERSION}:missing"
    market = MarketStore.open_readonly(market_path)
    if market is None or not market.has_symbol(SYMBOL, FEED):
        return f"{FINGERPRINT_VERSION}:missing"
    sessions = sorted(market.sessions(SYMBOL, FEED))
    if not sessions:
        return f"{FINGERPRINT_VERSION}:missing"
    relevant = sessions[-(LOOKBACK + SKIP + 1) :]
    hashes = dict(market.bar_hashes(SYMBOL, FEED, relevant[0], relevant[-1]))
    lines = [
        f"{session.isoformat()}:{open_}:{high}:{low}:{close}:{hashes.get(session, '')}"
        for session, open_, high, low, close in market.session_ohlc(
            SYMBOL, FEED, relevant[0], relevant[-1]
        )
    ]
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return f"{FINGERPRINT_VERSION}:{FEED}:{SYMBOL}:{len(lines)}:{relevant[-1].isoformat()}:{digest}"


def intent_authorized(
    store: ShadowStore,
    intent: dict[str, Any],
    *,
    now: datetime,
    policy: RiskPolicy | None = None,
) -> bool:
    """True only for a pending intent tied to a consumed grant or a live schedule."""
    evidence = intent.get("evidence")
    if not isinstance(evidence, dict) and intent.get("evidence_json"):
        try:
            evidence = json.loads(str(intent["evidence_json"]))
        except json.JSONDecodeError:
            return False
    if not isinstance(evidence, dict):
        return False
    auth = evidence.get("authorization")
    if not isinstance(auth, dict):
        return False
    if auth.get("scope") != SCOPE or auth.get("broker_orders") is not False:
        return False
    if auth.get("source") == "one_time":
        record = _load(store)
        return bool(
            record
            and record.get("status") == "consumed"
            and record.get("grant_id")
            and record.get("grant_id") == auth.get("grant_id")
            and record.get("broker_orders") is False
        )
    if auth.get("source") == "schedule":
        chosen = policy or RiskPolicy()
        binding = current_binding(
            ledger_version=0,
            policy=chosen,
            market_fingerprint="",
            preview_hash="",
        )
        schedule = _schedule_allows(store, binding, now)
        return schedule is not None and schedule.get("id") == auth.get("schedule_id")
    return False


def record_authorization_denial(store: ShadowStore, reason: str, *, now: datetime) -> None:
    """Persist a refused apply. This is an audit row, not a financial write."""
    _append_audit(
        store,
        {
            "at": now.isoformat(),
            "action": "approval_denied",
            "reason": reason[:300],
            "scope": SCOPE,
            "broker_orders": False,
        },
    )


def current_binding(
    *,
    ledger_version: int,
    policy: RiskPolicy,
    market_fingerprint: str,
    preview_hash: str,
) -> dict[str, Any]:
    return {
        "preview_hash": preview_hash,
        "ledger_version": ledger_version,
        "strategy_id": STRATEGY_ID,
        "policy_hash": policy.policy_hash(),
        "policy_version": policy.version,
        "feed": FEED,
        "market_fingerprint": market_fingerprint,
        "operation": OPERATION,
        "scope": SCOPE,
    }


def _load(store: ShadowStore) -> dict[str, Any] | None:
    raw = store.get_meta(APPROVAL_KEY)
    if not raw:
        return None
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        return None
    return loaded


def _require_match(record: dict[str, Any], binding: dict[str, Any], now: datetime) -> None:
    if record.get("status") != "pending":
        raise ValueError("shadow approval was already consumed")
    if record.get("scope") != SCOPE or record.get("broker_orders") is not False:
        raise ValueError("shadow approval scope is not an internal simulation")
    expires = datetime.fromisoformat(str(record.get("expires_at")))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        raise ValueError("shadow approval has expired")
    for key in (
        "preview_hash",
        "ledger_version",
        "strategy_id",
        "policy_hash",
        "feed",
        "market_fingerprint",
        "operation",
    ):
        if record.get(key) != binding.get(key):
            raise ValueError(f"shadow approval {key} does not match current state")


def _schedule_allows(
    store: ShadowStore, binding: dict[str, Any], now: datetime
) -> dict[str, Any] | None:
    record = _load_json(store, SCHEDULE_KEY)
    if record is None or record.get("status") != "enabled":
        return None
    if record.get("scope") != SCOPE or record.get("broker_orders") is not False:
        return None
    if record.get("operation") != OPERATION or record.get("strategy_id") != binding.get(
        "strategy_id"
    ):
        return None
    if record.get("feed") != binding.get("feed") or record.get("policy_hash") != binding.get(
        "policy_hash"
    ):
        return None
    expires = datetime.fromisoformat(str(record.get("expires_at")))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        return None
    return record


def _load_json(store: ShadowStore, key: str) -> dict[str, Any] | None:
    raw = store.get_meta(key)
    if not raw or raw == "enabled":
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _write_record(
    store: ShadowStore,
    key: str,
    record: dict[str, Any],
    *,
    action: str,
    now: datetime,
) -> None:
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR REPLACE INTO shadow_meta (key, value) VALUES (?, ?)",
            (key, json.dumps(record, sort_keys=True)),
        )
        _append_audit_conn(
            conn,
            {
                "at": now.isoformat(),
                "action": action,
                "grant_id": record.get("grant_id") or record.get("id"),
                "scope": SCOPE,
                "broker_orders": False,
            },
        )
        conn.commit()


def _append_audit(store: ShadowStore, event: dict[str, Any]) -> None:
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _append_audit_conn(conn, event)
        conn.commit()


def _append_audit_conn(conn: Any, event: dict[str, Any]) -> None:
    row = conn.execute("SELECT value FROM shadow_meta WHERE key = ?", (AUDIT_KEY,)).fetchone()
    raw = None if row is None else (row["value"] if hasattr(row, "keys") else row[0])
    try:
        events = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        events = []
    if not isinstance(events, list):
        events = []
    events.append(event)
    conn.execute(
        "INSERT OR REPLACE INTO shadow_meta (key, value) VALUES (?, ?)",
        (AUDIT_KEY, json.dumps(events[-200:], sort_keys=True)),
    )
