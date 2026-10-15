"""Deterministic signal helpers for long-only time-series momentum."""

from datetime import date
from decimal import Decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")


def momentum_return(
    closes: dict[date, Decimal],
    sessions: list[date],
    as_of: date,
    lookback: int,
    skip: int,
) -> Decimal | None:
    """Price return from ``lookback`` sessions ago to ``skip`` sessions ago.

    Uses only closes with session date strictly on or before ``as_of``.
    """
    available = [session for session in sessions if session <= as_of]
    needed = lookback + skip
    if len(available) < needed + 1:
        return None
    end_index = len(available) - 1 - skip
    start_index = end_index - lookback
    if start_index < 0 or end_index < 0:
        return None
    start_date = available[start_index]
    end_date = available[end_index]
    start_price = closes.get(start_date)
    end_price = closes.get(end_date)
    if start_price is None or end_price is None or start_price <= 0:
        return None
    return (end_price / start_price) - _ONE


def target_from_momentum(value: Decimal | None) -> Decimal:
    if value is None:
        return _ZERO
    return _ONE if value > 0 else _ZERO
