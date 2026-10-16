"""Calendar detection of month-start rebalances that were never recorded.

A miss is an audit fact. It is not a license to trade at an old open.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from nomadquant.marketdata.availability import latest_safe_session, modeled_available_at
from nomadquant.shadow.cycle import (
    _FORWARD_SIGNAL_MAX_AGE,
    FEED,
    LABEL_FORWARD,
    STRATEGY_ID,
    SYMBOL,
    _finish,
    _is_month_start,
)
from nomadquant.shadow.store import ShadowStore

PILOT_STARTED_KEY = "forward_pilot_started_at"


def classify_scheduled_signals(
    shadow: ShadowStore,
    sessions: list[date],
    now: datetime,
    *,
    label: str,
    persist_pilot_start: bool,
) -> list[dict[str, Any]]:
    """Classify each elapsed month-start. Does not create trades."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    pilot = _pilot_start(shadow, now, persist=persist_pilot_start and label == LABEL_FORWARD)
    calendar_latest = latest_safe_session(now, FEED)
    findings: list[dict[str, Any]] = []
    for session in _month_starts(sessions):
        available = modeled_available_at(session)
        if available > now:
            continue
        finding = _classify_one(
            shadow,
            session,
            now=now,
            available=available,
            pilot=pilot,
            calendar_latest=calendar_latest,
            label=label,
        )
        if finding is not None:
            findings.append(finding)
    return findings


def persist_missed_signals(
    shadow: ShadowStore,
    findings: list[dict[str, Any]],
    *,
    mode: str,
    label: str,
    before: dict[str, Any],
) -> list[dict[str, Any]]:
    """Write MISSED_SIGNAL rows on apply. Cash, holdings, and reservations stay put."""
    if mode != "apply" or label != LABEL_FORWARD:
        return [row for row in findings if row["classification"] == "missed_signal"]
    written: list[dict[str, Any]] = []
    for finding in findings:
        if finding["classification"] != "missed_signal":
            continue
        session = date.fromisoformat(finding["signal_session"])
        key = f"{label}:{FEED}:{SYMBOL}:{session.isoformat()}:{STRATEGY_ID}:missed_signal"
        evidence = {
            "classification": "missed_signal",
            "signal_session": session.isoformat(),
            "signal_available_at": finding["signal_available_at"],
            "detected_at": datetime.now(UTC).isoformat(),
            "pilot_started_at": finding["pilot_started_at"],
            "reason": (
                "The scheduled month-start rebalance was never recorded while it "
                "was still a prospective decision."
            ),
            "not_backfilled": True,
            "no_historical_fill": True,
        }
        detail = _finish(
            shadow,
            mode=mode,
            label=label,
            before=before,
            status="missed_signal",
            intent="no_trade",
            warnings=[
                f"MISSED_SIGNAL {session.isoformat()}: not backfilled."
            ],
            evidence=evidence,
            duration_ms=0,
            mutate=False,
            signal_session=session,
            cycle_key=key,
            error_safe="missed_signal",
        )
        written.append(detail)
    return written


def _classify_one(
    shadow: ShadowStore,
    session: date,
    *,
    now: datetime,
    available: datetime,
    pilot: datetime,
    calendar_latest: date,
    label: str,
) -> dict[str, Any] | None:
    cycles = [
        row
        for row in shadow.cycles_for_signal(session.isoformat())
        if row.get("label") in {None, label} and row.get("status") != "missed_signal"
    ]
    intents = shadow.intents_for_signal(session.isoformat())
    base = {
        "signal_session": session.isoformat(),
        "signal_available_at": available.isoformat(),
        "pilot_started_at": pilot.isoformat(),
    }
    if cycles or intents:
        pending = any(
            row.get("state") in {"PENDING_DATA", "SIGNAL_RECORDED", "RISK_APPROVED", "RESERVED"}
            for row in intents
        )
        open_cycle = any(
            row.get("status") in {"pending_data", "pending_observation"} for row in cycles
        )
        if pending or open_cycle:
            return {**base, "classification": "awaiting_observation"}
        return {**base, "classification": "finalized_prospective"}
    if session < pilot.astimezone(UTC).date():
        return {**base, "classification": "historical_only"}
    still_due = session == calendar_latest and (now - available) <= _FORWARD_SIGNAL_MAX_AGE
    if still_due:
        return {**base, "classification": "eligible_now"}
    return {**base, "classification": "missed_signal"}


def _pilot_start(shadow: ShadowStore, now: datetime, *, persist: bool) -> datetime:
    raw = shadow.get_meta(PILOT_STARTED_KEY)
    if raw:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    if persist:
        shadow.set_meta(PILOT_STARTED_KEY, now.isoformat())
    return now


def _month_starts(sessions: list[date]) -> list[date]:
    return [session for session in sessions if _is_month_start(session, sessions)]


def missed_signal_sessions(findings: list[dict[str, Any]]) -> set[date]:
    return {
        date.fromisoformat(row["signal_session"])
        for row in findings
        if row["classification"] == "missed_signal"
    }
