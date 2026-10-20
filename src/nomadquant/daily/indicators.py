"""Point-in-time indicators. Every input session must already be available."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from nomadquant.daily.registry import REVERSAL, TREND


def _ordered(closes: dict[date, Decimal], as_of: date) -> list[tuple[date, Decimal]]:
    rows = [(day, price) for day, price in closes.items() if day <= as_of and price > 0]
    return sorted(rows)


def sma(closes: dict[date, Decimal], as_of: date, window: int) -> Decimal | None:
    rows = _ordered(closes, as_of)
    if len(rows) < window:
        return None
    chosen = [price for _day, price in rows[-window:]]
    return sum(chosen, Decimal("0")) / Decimal(window)


def trailing_return(closes: dict[date, Decimal], as_of: date, sessions: int) -> Decimal | None:
    rows = _ordered(closes, as_of)
    if len(rows) <= sessions:
        return None
    start = rows[-(sessions + 1)][1]
    end = rows[-1][1]
    if start <= 0:
        return None
    return end / start - Decimal("1")


def daily_returns(closes: dict[date, Decimal], as_of: date, window: int) -> list[Decimal] | None:
    rows = _ordered(closes, as_of)
    if len(rows) < window + 1:
        return None
    chosen = rows[-(window + 1) :]
    result: list[Decimal] = []
    for previous, current in zip(chosen, chosen[1:], strict=False):
        if previous[1] <= 0:
            return None
        result.append(current[1] / previous[1] - Decimal("1"))
    return result


def sample_stdev(values: list[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
    return variance.sqrt()


def realized_vol(closes: dict[date, Decimal], as_of: date, window: int) -> Decimal | None:
    returns = daily_returns(closes, as_of, window)
    if returns is None:
        return None
    return sample_stdev(returns)


def trend_snapshot(closes: dict[date, Decimal], as_of: date) -> dict[str, str | None]:
    average = sma(closes, as_of, 200)
    vol = realized_vol(closes, as_of, 20)
    rows = _ordered(closes, as_of)
    close = None if not rows else rows[-1][1]
    return {
        "strategy_id": TREND.strategy_id,
        "close": None if close is None else format(close, "f"),
        "sma_200": None if average is None else format(average, "f"),
        "vol_20": None if vol is None else format(vol, "f"),
    }


def reversal_snapshot(closes: dict[date, Decimal], as_of: date) -> dict[str, str | None]:
    move = trailing_return(closes, as_of, 5)
    history: list[Decimal] = []
    rows = _ordered(closes, as_of)
    if len(rows) >= 66:
        for index in range(len(rows) - 60, len(rows)):
            day = rows[index][0]
            value = trailing_return(closes, day, 5)
            if value is not None:
                history.append(value)
    dispersion = sample_stdev(history) if len(history) >= 20 else None
    return {
        "strategy_id": REVERSAL.strategy_id,
        "return_5": None if move is None else format(move, "f"),
        "dispersion": None if dispersion is None else format(dispersion, "f"),
    }
