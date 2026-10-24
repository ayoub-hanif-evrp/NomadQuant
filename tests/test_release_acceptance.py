"""Release checks that stay inside a temporary directory."""

from pathlib import Path

from nomadquant.broker.verify_account import verify_paper_account
from tests.conftest import make_settings


def test_missing_credentials_block_verification_without_a_broker_call(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    report = verify_paper_account(settings)
    assert report["readiness"] == "blocked"
    assert report["reason"] == "credentials_absent"
    assert report["broker_orders_submitted_by_this_request"] is False
    assert report["authorization_changed"] is False
    assert report["history_rewritten"] is False
    assert report["sleeve_is_not_broker_cash"] is True
    assert report["internal_allocation_usd"] == "100"
    assert report["next_action"].startswith("Do not submit.")
    assert not (tmp_path / "paper_orders.sqlite").exists()
