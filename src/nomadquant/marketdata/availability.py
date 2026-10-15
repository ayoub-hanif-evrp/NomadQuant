"""Modeled availability for a completed US cash session.

A daily bar's timestamp is the start of that session, not the time a reader
may use the close. This module uses 16:30 America/New_York on the session
date. That is later than the 16:00 cash close and later than a 13:00 early
close, so it is conservative for both.

Limitations: 16:30 is a model. It is not the vendor's publication time, and a
download performed today does not prove that this close was visible at 16:30
on the historical session. Later corrections are a separate revision problem.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nomadquant.marketdata.calendar import previous_session, sessions_between

NEW_YORK = ZoneInfo("America/New_York")
AVAILABLE_LOCAL = time(16, 30)


def session_date_from_timestamp(timestamp: datetime) -> date:
    aware = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
    return aware.astimezone(NEW_YORK).date()


def modeled_available_at(session: date) -> datetime:
    local = datetime.combine(session, AVAILABLE_LOCAL, tzinfo=NEW_YORK)
    return local.astimezone(UTC)


def latest_completed_session(now: datetime) -> date:
    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    aware = aware.astimezone(UTC)
    window_start = (aware - timedelta(days=14)).date()
    completed = [
        session
        for session in sessions_between(window_start, aware.date())
        if modeled_available_at(session) <= aware
    ]
    if completed:
        return completed[-1]
    return previous_session(aware.date())
