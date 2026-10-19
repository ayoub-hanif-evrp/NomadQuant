"""Home copy must not call an armed clock a running worker or an authorized fill."""

from nomadquant.overview import _pilot_check


def test_armed_clock_is_not_described_as_a_running_fill() -> None:
    armed = _pilot_check(True, False)
    assert armed["title"] == "Forward clock is armed"
    assert "approve" in armed["detail"]
    assert "running" not in armed["title"].lower()


def test_missing_clock_says_the_pilot_has_not_started() -> None:
    idle = _pilot_check(False, False)
    assert idle["title"] == "Forward pilot has not been started"
