"""A closed market day must not be described as a pending trade."""

from datetime import UTC, date, datetime

from nomadquant.shadow.preflight import observation_waiting_detail


def test_non_rebalance_day_does_not_claim_a_pending_signal() -> None:
    text = observation_waiting_detail(
        date(2026, 10, 19),
        datetime(2026, 10, 19, 20, 30, tzinfo=UTC),
        rebalance_due=False,
    )
    assert "no signal is waiting" in text
    assert "pending" not in text


def test_rebalance_day_says_the_signal_waits_for_the_open() -> None:
    text = observation_waiting_detail(
        date(2026, 11, 3),
        datetime(2026, 11, 3, 21, 30, tzinfo=UTC),
        rebalance_due=True,
    )
    assert "recorded as pending" in text
