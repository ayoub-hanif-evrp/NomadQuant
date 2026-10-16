"""Supervised pilot checks stay read-only and do not create a ledger."""

from pathlib import Path

from nomadquant.config import Settings
from nomadquant.shadow.pilot import supervised_readiness


def test_missing_ledger_is_insufficient_and_not_created(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.sqlite"
    settings = Settings(
        market_data_path=str(tmp_path / "market.sqlite"),
        shadow_path=str(shadow),
        risk_path=str(tmp_path / "risk.sqlite"),
    )
    report = supervised_readiness(settings)
    assert report["mutates_forward_ledger"] is False
    assert report["broker_orders"] is False
    assert report["readiness"] == "NOT_CONFIGURED"
    assert report["pilot_running"] is False
    assert report["rebalance_scheduled"] is False
    assert report["user_decision_required"] is True
    assert report["pilot_active"] is False
    assert shadow.exists() is False
