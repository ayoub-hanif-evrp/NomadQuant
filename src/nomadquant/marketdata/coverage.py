"""Compare stored sessions with the NYSE sessions in a requested window."""

from datetime import date, datetime, timedelta

from nomadquant.marketdata.availability import (
    modeled_available_at,
    session_bar_timestamp,
    session_date_from_timestamp,
)
from nomadquant.marketdata.calendar import sessions_between


def classify_missing(
    expected: list[date],
    stored: set[date],
) -> tuple[list[date], list[date], list[date]]:
    """Split missing sessions into the start, middle, and end of ``expected``."""
    missing = [session for session in expected if session not in stored]
    present = [session for session in expected if session in stored]
    if not missing or not present:
        return missing, [], []
    first_present = present[0]
    last_present = present[-1]
    begin = [session for session in missing if session < first_present]
    middle = [session for session in missing if first_present < session < last_present]
    end = [session for session in missing if session > last_present]
    return begin, middle, end


def missing_in_window(
    stored: set[date],
    start: date,
    end: date,
) -> tuple[list[date], list[date], list[date]]:
    return classify_missing(sessions_between(start, end), stored)


def knowable_sessions(start: datetime, end: datetime, as_of: datetime) -> list[date]:
    """Sessions whose daily bar is inside the timestamp window and knowable at ``as_of``.

    A session whose modeled availability is later than ``as_of`` is withheld by
    the information cutoff. It is not treated as missing.
    """
    first = session_date_from_timestamp(start) - timedelta(days=7)
    last = session_date_from_timestamp(end) + timedelta(days=1)
    return [
        session
        for session in sessions_between(first, last)
        if start <= session_bar_timestamp(session) <= end and modeled_available_at(session) <= as_of
    ]
