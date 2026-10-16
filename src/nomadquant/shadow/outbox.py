"""Idempotent outbox delivery from shadow DB to risk/audit stores."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nomadquant.risk.store import RiskStore
from nomadquant.shadow.store import ShadowStore


def deliver_outbox(
    shadow: ShadowStore,
    risk_path: str | Path,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Publish undelivered outbox rows. Safe to retry; never mutates ledger cash."""
    delivered = 0
    errors: list[str] = []
    risk = RiskStore(risk_path)
    rows = shadow.list_outbox(undelivered_only=True, limit=limit)
    for row in rows:
        try:
            kind = row["kind"]
            payload = (
                row["payload"]
                if isinstance(row["payload"], dict)
                else json.loads(row["payload_json"])
            )
            if kind == "risk_evaluation":
                # Derived audit only — shadow ledger remains source of truth.
                risk.record_projection(payload)
            shadow.mark_outbox_delivered(int(row["id"]))
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            shadow.mark_outbox_attempt(int(row["id"]), error=str(exc))
            errors.append(f"outbox:{row['id']}:{exc}")
    return {
        "delivered": delivered,
        "errors": errors,
        "remaining": len(shadow.list_outbox(undelivered_only=True, limit=1000)),
        "as_of": datetime.now(UTC).isoformat(),
    }
