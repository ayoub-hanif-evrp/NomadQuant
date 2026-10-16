"""America/New_York eligibility gate. Host timezone is not assumed."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from nomadquant.marketdata.calendar import is_session, next_session, previous_session

_NY = ZoneInfo("America/New_York")
_GATE = time(17, 45)


def ny_daily_gate(
    now: datetime, *, last_processed_session: date | None = None
) -> dict[str, object]:
    """Decide whether a daily worker run is due.

    Eligibility uses America/New_York and the NYSE calendar. A missed 17:45
    window stays due until that session is recorded as processed. Weekends and
    holidays do not create a new session; they can still catch up the previous one.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    ny = now.astimezone(_NY)
    due = _due_session(ny)
    if due is None:
        return _payload(ny, eligible=False, due=None, reason="no_completed_session")
    if last_processed_session is not None and last_processed_session >= due:
        return _payload(ny, eligible=False, due=due, reason="already_processed")
    today = ny.date()
    after = _after_gate(ny)
    if is_session(today) and after and due == today:
        reason = "eligible"
    elif not is_session(today):
        reason = "catch_up_closed_day"
    else:
        reason = "catch_up"
    return _payload(ny, eligible=True, due=due, reason=reason)


def next_ny_window(now: datetime) -> dict[str, object]:
    """Next 17:45 America/New_York on an NYSE session, as an absolute instant."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    ny = now.astimezone(_NY)
    day = ny.date()
    if is_session(day) and not _after_gate(ny):
        target = day
    elif is_session(day):
        target = next_session(day)
    else:
        target = next_session(day)
    local = datetime(target.year, target.month, target.day, 17, 45, tzinfo=_NY)
    return {
        "session": target.isoformat(),
        "ny_local": local.isoformat(),
        "utc": local.astimezone(ZoneInfo("UTC")).isoformat(),
    }


def _due_session(ny: datetime) -> date | None:
    today = ny.date()
    if is_session(today) and _after_gate(ny):
        return today
    try:
        return previous_session(today)
    except RuntimeError:
        return None


def _after_gate(ny: datetime) -> bool:
    return ny.timetz().replace(tzinfo=None) >= _GATE


def _payload(ny: datetime, *, eligible: bool, due: date | None, reason: str) -> dict[str, object]:
    upcoming = next_ny_window(ny)
    return {
        "eligible": eligible,
        "ny_local": ny.isoformat(),
        "weekend": ny.weekday() >= 5,
        "after_1745": _after_gate(ny),
        "due_session": None if due is None else due.isoformat(),
        "reason": reason,
        "next_window_ny": upcoming["ny_local"],
        "next_window_utc": upcoming["utc"],
    }
