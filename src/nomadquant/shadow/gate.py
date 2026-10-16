"""Single fail-closed gate for forward shadow application. No broker orders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.shadow.preflight import run_preflight, run_reconcile
from nomadquant.shadow.store import ShadowStore


def application_guard(settings: Settings) -> dict[str, Any]:
    """Authoritative check before any forward ledger mutation.

    Used by the worker and by ``cycle --mode apply``. Dry-run does not call this
    to mutate; apply must refuse when this returns ``allowed=False``.
    """
    preflight = run_preflight(settings)
    reconcile = run_reconcile(settings)
    shadow_file = Path(settings.shadow_path)
    active: list[dict[str, Any]] = []
    if shadow_file.exists():
        store = ShadowStore.open_readonly(settings.shadow_path)
        active = [] if store is None else store.list_active_reservations()
    reasons: list[str] = []
    if preflight.get("status") == "BLOCKED":
        reasons.append("preflight_blocked")
    issues = list(reconcile.get("issues") or [])
    if not reconcile.get("ok") and issues != ["shadow_uninitialized"]:
        reasons.append("reconcile_failed")
    if active:
        reasons.append("active_reservations")
    if settings.allow_order_submission:
        reasons.append("order_submission_enabled")
    return {
        "allowed": len(reasons) == 0,
        "reasons": reasons,
        "preflight_status": preflight.get("status"),
        "reconcile_ok": bool(reconcile.get("ok")),
        "active_reservations": len(active),
        "preflight": preflight,
        "reconcile": reconcile,
        "note": "Forward apply only. Does not submit broker orders.",
    }
