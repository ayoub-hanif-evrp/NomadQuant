"""Pilot preview is read-only and confirmation rejects a stale token."""

from pathlib import Path

from nomadquant.config import Settings
from nomadquant.shadow.pilot import confirm_pilot_start, pilot_start_preview
from nomadquant.shadow.store import ShadowStore


def test_preview_does_not_mutate_and_stale_token_is_rejected(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.sqlite"
    opened = ShadowStore(shadow, namespace="forward")
    before = opened.snapshot()
    settings = Settings(
        market_data_path=str(tmp_path / "market.sqlite"),
        shadow_path=str(shadow),
        risk_path=str(tmp_path / "risk.sqlite"),
    )
    preview = pilot_start_preview(settings)
    assert preview["mutates_forward_ledger"] is False
    assert preview["broker_orders"] is False
    assert "preview_hash" in preview
    after = ShadowStore(shadow, namespace="forward").snapshot()
    assert after["version"] == before["version"]
    assert after["cash_usd"] == before["cash_usd"]
    rejected = confirm_pilot_start(settings, "0" * 64)
    assert rejected["status"] == "REJECTED"
    assert rejected["applied"] is False
    accepted = confirm_pilot_start(settings, preview["preview_hash"])
    assert accepted["applied"] is False
    assert accepted["stored"] is True
    assert accepted["fill_grant_issued"] is False
    assert accepted["status"] == "PILOT_ARMED"
    assert ShadowStore(shadow, namespace="forward").snapshot()["version"] == 1
    assert ShadowStore(shadow, namespace="forward").get_meta("shadow_apply_approval") is None
    assert ShadowStore(shadow, namespace="forward").get_meta("forward_pilot_started_at")
