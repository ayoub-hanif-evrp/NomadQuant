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
    """Registered ``spy-tsmom-v1`` return. Do not change this formula in place.

    momentum = close[t - skip] / close[t - skip - lookback] - 1

    For lookback 252 and skip 21 that is 252 return intervals ending 21
    sessions before the decision. The guard requires lookback + skip + 1
    sessions (274). Fewer sessions returns None.

    A different published reading uses close[t - skip] / close[t - lookback] - 1,
    which is only lookback - skip intervals. That is not this experiment.
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
    """Map a computed momentum number to a long-only weight.

    Positive momentum targets 1. Zero and negative momentum target cash.
    ``None`` is unavailable data, not a cash signal.
    """
    if value is None:
        raise ValueError("INSUFFICIENT_DATA: momentum is unavailable and is not a cash target")
    return _ONE if value > 0 else _ZERO
