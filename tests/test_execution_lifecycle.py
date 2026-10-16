"""Fake order lifecycle. UNKNOWN is not a failure and is not retried."""

from decimal import Decimal

import pytest

from nomadquant.broker.capabilities import broker_capability_profile
from nomadquant.execution.lifecycle import BlindRetryForbidden, run_script
from nomadquant.quality import quality_report
from tests.conftest import make_settings


def test_unknown_timeout_is_not_a_failure_and_blocks_retry() -> None:
    order = run_script(
        "cid-1",
        ["risk_checked", "reserved", "submitted", "timeout"],
        quantity=Decimal("1"),
    )
    assert order.state == "unknown"
    assert order.attempts == 1
    with pytest.raises(BlindRetryForbidden):
        run_script("cid-1", ["risk_checked", "reserved", "submitted", "timeout", "retry"])


def test_crash_reservation_and_commit_are_distinct() -> None:
    reserved = run_script("cid-2", ["risk_checked", "reserved", "crash_after_reservation"])
    assert reserved.reserved is True
    assert reserved.ledger_committed is False
    committed = run_script(
        "cid-3",
        ["risk_checked", "reserved", "submitted", "filled", "crash_after_commit", "replay_commit"],
    )
    assert committed.ledger_committed is True
    assert committed.warnings[-1] == "Commit replay was idempotent."


def test_partial_duplicate_and_out_of_order_updates() -> None:
    partial = run_script(
        "cid-4",
        ["risk_checked", "reserved", "submitted", "partial_fill", "duplicate"],
    )
    assert partial.state == "partial"
    assert partial.filled_qty == Decimal("0.5")
    assert "Duplicate update ignored." in partial.warnings
    early = run_script("cid-5", ["out_of_order_fill"])
    assert early.state != "filled"
    assert any("before submission" in item for item in early.warnings)


def test_broker_lookup_keeps_an_absent_record_unknown() -> None:
    found = run_script(
        "cid-6",
        ["risk_checked", "reserved", "submitted", "timeout", "broker_lookup"],
        broker_state="accepted",
    )
    assert found.state == "reconciled"
    absent = run_script(
        "cid-7",
        ["risk_checked", "reserved", "submitted", "timeout", "broker_lookup"],
    )
    assert absent.state == "unknown"


def test_capability_profile_does_not_assume_paper_cash_or_enable_orders() -> None:
    profile = broker_capability_profile()
    assert profile["order_submission_implemented"] is False
    assert profile["paper_balance_assumed_usd"] is None
    assert profile["internal_capital_constraint_usd"] == "100"
    assert profile["paper_reset"]["action_taken"] == "none"
    assert profile["fractional_shares"]["spy_fractionable"] == "NOT_QUERIED"


def test_quality_report_stays_read_only(tmp_path) -> None:
    settings = make_settings(tmp_path)
    report = quality_report(settings)
    assert report["execution_convention"] == "half_spread_plus_full_slippage_v1"
    assert report["cost_scenarios"]["base_buy"] == "100.015"
    assert report["cost_scenarios"]["stress_buy"] != report["cost_scenarios"]["base_buy"]
    assert report["broker"]["order_submission_implemented"] is False
    assert report["ci"]["result"] == "NOT_RECORDED_IN_PROCESS"
    assert not (tmp_path / "shadow.sqlite").exists()
