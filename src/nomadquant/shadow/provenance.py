"""Bar provenance for shadow fills. Daily OHLC is never a real-time execution."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nomadquant.marketdata.store import StoredBar

EXECUTION_DELAYED_HYPOTHETICAL = "delayed_hypothetical_daily_open"


def provenance_dict(bar: StoredBar, *, evaluated_at: datetime) -> dict[str, Any]:
    retrieved = bar.first_retrieved_at
    realtime = False
    gaps: list[str] = []
    if retrieved.tzinfo is None:
        gaps.append("first_retrieved_at_naive")
    elif retrieved > evaluated_at:
        gaps.append("bar_retrieved_after_evaluation_clock")
    return {
        "symbol": bar.symbol,
        "session": bar.session_date.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "provider": bar.provider,
        "feed": bar.feed,
        "adjustment": bar.adjustment,
        "bar_timestamp": bar.timestamp.isoformat(),
        "modeled_available_at": bar.available_at.isoformat(),
        "first_retrieved_at": retrieved.isoformat(),
        "content_hash": bar.content_hash,
        "execution_assumption": EXECUTION_DELAYED_HYPOTHETICAL,
        "realtime_executable": realtime,
        "evidence_gaps": gaps,
        "note": (
            "Open from a stored daily bar is a delayed hypothetical fill input. "
            "It is not proof the system could have traded at the open."
        ),
    }
