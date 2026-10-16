"""One-time internal shadow-apply approval. Not a broker order authorization."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nomadquant.risk.policy import RiskPolicy
from nomadquant.shadow.cycle import FEED, STRATEGY_ID
from nomadquant.shadow.store import ShadowStore

APPROVAL_KEY = "shadow_apply_approval"
SCHEDULE_KEY = "scheduled_shadow_cycles"
APPROVABLE_STATES = frozenset({"READY_TO_START"})
APPROVAL_TTL = timedelta(minutes=30)
SCOPE = "internal_shadow_simulation_only"
OPERATION = "forward_shadow_apply"


def state_can_be_approved(state: str) -> bool:
    return state in APPROVABLE_STATES


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
        "status": "pending",
        "scope": SCOPE,
        "operation": OPERATION,
        "broker_orders": False,
        "issued_at": now.isoformat(),
        "expires_at": (now + APPROVAL_TTL).isoformat(),
        "consumed_at": None,
    }
    store.set_meta(APPROVAL_KEY, json.dumps(record, sort_keys=True))
    return record


def enable_scheduled_shadow_cycles(store: ShadowStore) -> None:
    """Explicit later-cycle policy. Pilot confirmation must not call this."""
    store.set_meta(SCHEDULE_KEY, "enabled")


def scheduled_shadow_cycles_enabled(store: ShadowStore) -> bool:
    return store.get_meta(SCHEDULE_KEY) == "enabled"


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
    conn.execute(
        "UPDATE shadow_meta SET value = ? WHERE key = ?",
        (json.dumps(record, sort_keys=True), APPROVAL_KEY),
    )


def approval_decision(
    store: ShadowStore, binding: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Decide whether a new forward apply may proceed. Does not consume."""
    if scheduled_shadow_cycles_enabled(store):
        return {"allowed": True, "consume": False, "reason": "scheduled_policy"}
    record = _load(store)
    if record is None:
        return {"allowed": False, "consume": False, "reason": "missing_shadow_approval"}
    try:
        _require_match(record, binding, now)
    except ValueError as exc:
        return {"allowed": False, "consume": False, "reason": str(exc)}
    return {"allowed": True, "consume": True, "reason": "one_time_approval", "binding": binding}


def market_fingerprint(market_path: Path) -> str:
    """Stable description of the stored SIP SPY sessions. Empty coverage is explicit."""
    from nomadquant.marketdata.store import MarketStore

    if not market_path.is_file():
        return "missing"
    market = MarketStore.open_readonly(market_path)
    if market is None or not market.has_symbol("SPY", FEED):
        return "missing"
    sessions = list(market.sessions("SPY", FEED))
    latest = max(sessions).isoformat() if sessions else "none"
    return f"{FEED}:SPY:{len(sessions)}:{latest}"


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
