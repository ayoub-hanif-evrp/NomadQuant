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
# Alpaca withholds the latest 15 minutes of SIP from unpaid historical queries.
# The extra 15 minutes keeps a request end out of that window despite clock skew.
SIP_RECENT_WINDOW = timedelta(minutes=15)
SIP_SAFETY_MARGIN = timedelta(minutes=30)
OTHER_FEED_MARGIN = timedelta(minutes=1)


def session_date_from_timestamp(timestamp: datetime) -> date:
    aware = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
    return aware.astimezone(NEW_YORK).date()


def modeled_available_at(session: date) -> datetime:
    local = datetime.combine(session, AVAILABLE_LOCAL, tzinfo=NEW_YORK)
    return local.astimezone(UTC)


def session_bar_timestamp(session: date) -> datetime:
    """Canonical daily-bar timestamp: midnight America/New_York, in UTC."""
    local = datetime.combine(session, time.min, tzinfo=NEW_YORK)
    return local.astimezone(UTC)


def historical_request_end(session: date, now: datetime, feed: str) -> datetime:
    """Latest UTC instant that still includes this session's daily bar.

    The bound is never in the future. For SIP it is also at least 30 minutes
    before ``now``, which is outside Alpaca's recent 15-minute SIP restriction.
    """
    from nomadquant.marketdata.errors import IncompleteSession

    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    aware = aware.astimezone(UTC)
    next_utc_day = datetime(session.year, session.month, session.day, tzinfo=UTC)
    coverage_end = next_utc_day + timedelta(days=1)
    margin = SIP_SAFETY_MARGIN if feed == "sip" else OTHER_FEED_MARGIN
    ceiling = aware - margin
    bound = min(coverage_end, ceiling)
    bar_timestamp = session_bar_timestamp(session)
    if bound <= bar_timestamp or bound > aware:
        raise IncompleteSession(
            f"{session.isoformat()} is too recent for a {feed} historical request. "
            "The request end would be in the future or inside Alpaca's recent SIP "
            "window. Omit --end to use the latest safe completed session, or pass "
            "an older explicit --end."
        )
    return bound


def latest_safe_session(now: datetime, feed: str) -> date:
    """Latest NYSE session that is model-available and safe to request."""
    from nomadquant.marketdata.errors import IncompleteSession

    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    aware = aware.astimezone(UTC)
    window_start = (aware - timedelta(days=14)).date()
    eligible = [
        session
        for session in sessions_between(window_start, aware.date())
        if modeled_available_at(session) <= aware and _request_is_safe(session, aware, feed)
    ]
    if eligible:
        return eligible[-1]
    fallback = previous_session(aware.date())
    try:
        historical_request_end(fallback, aware, feed)
    except IncompleteSession:
        raise IncompleteSession(
            "No completed NYSE session is outside the recent historical-request window."
        ) from None
    return fallback


def _request_is_safe(session: date, now: datetime, feed: str) -> bool:
    from nomadquant.marketdata.errors import IncompleteSession

    try:
        historical_request_end(session, now, feed)
    except IncompleteSession:
        return False
    return True


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
