"""Shared fixtures for forward shadow-apply tests. Not a broker authorization."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from nomadquant.risk.policy import RiskPolicy
from nomadquant.shadow.approval import current_binding, issue_shadow_approval, market_fingerprint
from nomadquant.shadow.store import ShadowStore


def grant_forward_approval(shadow_path: Path, market_path: Path, now: datetime) -> None:
    """Store one matching internal-shadow approval for an isolated test ledger."""
    store = ShadowStore(shadow_path, namespace="forward")
    binding = current_binding(
        ledger_version=int(store.snapshot()["version"]),
        policy=RiskPolicy(),
        market_fingerprint=market_fingerprint(market_path),
        preview_hash="test-authorization",
    )
    issue_shadow_approval(store, binding, now=now)
