"""XNYS session calendar. Weekdays are not assumed to be trading days."""

from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import exchange_calendars as exchange_calendars
import pandas as pd

NYSE = "XNYS"


@lru_cache(maxsize=1)
def _calendar() -> Any:
    return exchange_calendars.get_calendar(NYSE)


def is_session(day: date) -> bool:
    calendar = _calendar()
    return bool(calendar.is_session(pd.Timestamp(day)))


def is_early_close(day: date) -> bool:
    if not is_session(day):
        return False
    early = {stamp.date() for stamp in _calendar().early_closes}
    return day in early


def sessions_between(start: date, end: date) -> list[date]:
    if start > end:
        return []
    calendar = _calendar()
    index = calendar.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
    return [stamp.date() for stamp in index]


def previous_session(day: date) -> date:
    cursor = day - timedelta(days=1)
    for _ in range(14):
        if is_session(cursor):
            return cursor
        cursor -= timedelta(days=1)
    raise RuntimeError("No NYSE session was found in the previous two weeks.")


def next_session(day: date) -> date:
    cursor = day + timedelta(days=1)
    for _ in range(14):
        if is_session(cursor):
            return cursor
        cursor += timedelta(days=1)
    raise RuntimeError("No NYSE session was found in the next two weeks.")
